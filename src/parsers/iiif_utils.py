"""IIIF Presentation API 유틸리티 — 매니페스트 파싱, 메타데이터 추출, 이미지 다운로드.

왜 별도 모듈인가:
    NDL(dl.ndl.go.jp)과 NIJL(kokusho.nijl.ac.jp) 모두 IIIF Presentation API 2.0을
    사용한다. 재사용 가능한 유틸리티로 분리하여 중복 코드를 방지한다.

IIIF Presentation API 2.0 구조 요약:
    manifest.json → {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "label": "제목",
        "metadata": [{"label": "...", "value": "..."}, ...],
        "sequences": [{
            "canvases": [{
                "label": "p. 1",
                "images": [{
                    "resource": {"@id": "https://.../default.jpg", ...}
                }]
            }]
        }]
    }

사용 예시:
    manifest = await fetch_iiif_manifest(url)
    meta = extract_iiif_metadata(manifest)
    canvases = extract_iiif_canvases(manifest)
    pdf_path = await download_iiif_images_as_pdf(canvases, dest_dir)
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ──────────────────────────────────────
# IIIF manifest 조회
# ──────────────────────────────────────


async def fetch_iiif_manifest(manifest_url: str) -> dict[str, Any]:
    """IIIF manifest.json을 가져온다.

    입력: manifest_url — IIIF Presentation API manifest URL.
    출력: manifest JSON dict.
    에러: httpx.HTTPStatusError — 네트워크 오류 시.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(manifest_url)
        response.raise_for_status()
        return response.json()


# ──────────────────────────────────────
# 메타데이터 추출
# ──────────────────────────────────────

# IIIF metadata label 변형 매핑.
# 기관마다 label이 다를 수 있으므로 여러 형태를 하나의 키로 통일한다.
# 예: NDL은 "Title", kokusho는 "タイトル" 등.
_LABEL_MAP: dict[str, str] = {
    # title
    "title": "title",
    "タイトル": "title",
    "書名": "title",
    "label": "title",
    # creator
    "creator": "creator",
    "author": "creator",
    "著者": "creator",
    "作者": "creator",
    # publisher
    "publisher": "publisher",
    "出版者": "publisher",
    "発行者": "publisher",
    # date
    "date": "date",
    "date published": "date",
    "出版年": "date",
    "刊行年": "date",
    # call_number
    "call number": "call_number",
    "請求記号": "call_number",
    # doi
    "doi": "doi",
    # description
    "description": "description",
    "解題": "description",
}


def extract_iiif_metadata(manifest: dict[str, Any]) -> dict[str, Any]:
    """IIIF manifest의 metadata 배열에서 서지정보를 추출한다.

    입력: manifest — fetch_iiif_manifest()가 반환한 dict.
    출력: {"title", "creator", "publisher", "date", "call_number",
           "doi", "description", "attribution", "license"} — 없는 필드는 None.

    왜 이렇게 하는가:
        IIIF manifest의 metadata는 [{label, value}] 배열이다.
        label은 기관마다 다를 수 있으므로 _LABEL_MAP으로 정규화한다.
        label/value가 문자열 또는 {"@value": "...", "@language": "..."} 객체일 수 있다.
    """
    result: dict[str, Any] = {
        "title": None,
        "creator": None,
        "publisher": None,
        "date": None,
        "call_number": None,
        "doi": None,
        "description": None,
        "attribution": None,
        "license": None,
    }

    # manifest 최상위 label → title 폴백
    top_label = manifest.get("label")
    if top_label:
        result["title"] = _extract_label_value(top_label)

    # attribution
    attribution = manifest.get("attribution")
    if attribution:
        result["attribution"] = _extract_label_value(attribution)

    # license
    license_val = manifest.get("license")
    if license_val:
        result["license"] = license_val if isinstance(license_val, str) else str(license_val)

    # metadata 배열 처리
    for entry in manifest.get("metadata", []):
        label_raw = entry.get("label", "")
        value_raw = entry.get("value", "")

        label_str = _extract_label_value(label_raw).lower().strip()
        value_str = _extract_label_value(value_raw)

        if not label_str or not value_str:
            continue

        mapped_key = _LABEL_MAP.get(label_str)
        if mapped_key and result.get(mapped_key) is None:
            result[mapped_key] = value_str

    return result


def _extract_label_value(raw: Any) -> str:
    """IIIF label/value 필드에서 문자열을 추출한다.

    왜 이렇게 하는가:
        IIIF 2.0은 label/value가 단순 문자열일 수도 있고,
        {"@value": "...", "@language": "ja"} 객체일 수도 있다.
        IIIF 3.0은 {"ko": ["값"]} 형태를 사용한다.
        모든 경우를 통일한다.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        # IIIF 2.0: {"@value": "...", "@language": "..."}
        if "@value" in raw:
            return str(raw["@value"])
        # IIIF 3.0: {"ja": ["値"], "en": ["Value"]}
        for values in raw.values():
            if isinstance(values, list) and values:
                return str(values[0])
    if isinstance(raw, list) and raw:
        # 배열인 경우 첫 번째 요소
        return _extract_label_value(raw[0])
    return str(raw) if raw else ""


# ──────────────────────────────────────
# 캔버스(페이지) 목록 추출
# ──────────────────────────────────────


def extract_iiif_canvases(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """IIIF manifest에서 캔버스(페이지) 목록을 추출한다.

    입력: manifest dict.
    출력: [{
        "canvas_index": int,    # 0-based
        "label": str,           # "p. 1" 등
        "image_url": str,       # full-size image URL
        "width": int | None,
        "height": int | None,
    }, ...]

    왜 이렇게 하는가:
        IIIF Presentation API 2.0의 sequences[0].canvases를 순회하여
        각 캔버스의 첫 번째 이미지 URL과 크기를 추출한다.
    """
    canvases = []

    sequences = manifest.get("sequences", [])
    if not sequences:
        logger.warning("IIIF manifest에 sequences가 없습니다.")
        return canvases

    canvas_list = sequences[0].get("canvases", [])

    for idx, canvas in enumerate(canvas_list):
        label = _extract_label_value(canvas.get("label", f"p. {idx + 1}"))

        # images[0].resource에서 이미지 URL 추출
        images = canvas.get("images", [])
        if not images:
            continue

        resource = images[0].get("resource", {})
        image_url = resource.get("@id")
        if not image_url:
            continue

        width = resource.get("width") or canvas.get("width")
        height = resource.get("height") or canvas.get("height")

        canvases.append({
            "canvas_index": idx,
            "label": label,
            "image_url": image_url,
            "width": width,
            "height": height,
        })

    return canvases


# ──────────────────────────────────────
# 이미지 다운로드 → PDF 변환
# ──────────────────────────────────────


def _resize_iiif_url(image_url: str, max_dim: int) -> str:
    """IIIF Image API URL의 size 파라미터를 변경하여 이미지를 축소한다.

    IIIF Image API 2.x URL 구조:
        {scheme}://{server}{/prefix}/{identifier}/{region}/{size}/{rotation}/{quality}.{format}

    예시:
        원본: https://dl.ndl.go.jp/api/iiif/1193135/R0000001/full/full/0/default.jpg
        축소: https://dl.ndl.go.jp/api/iiif/1193135/R0000001/full/!1500,1500/0/default.jpg

    왜 축소하는가:
        NDL 이미지는 최대 5113x4877 픽셀이다. full 크기로 161페이지를 받으면
        수 GB에 달해 다운로드 시간이 비현실적이다.
        !{w},{h}는 "종횡비를 유지하면서 w×h 안에 맞추기" 의미이다.
    """
    return re.sub(r"/full/full/", f"/full/!{max_dim},{max_dim}/", image_url)


def _sanitize_filename(name: str) -> str:
    """파일명으로 안전한 문자열을 만든다."""
    safe = re.sub(r'[<>:"/\\|?*]', "_", name)
    return safe[:100] if safe else "untitled"


async def download_iiif_images_as_pdf(
    canvases: list[dict[str, Any]],
    dest_dir: Path,
    label: str = "iiif_download",
    progress_callback: Callable[[int, int], None] | None = None,
    max_dimension: int | None = 1500,
) -> Path:
    """IIIF 캔버스 이미지를 다운로드하여 PDF로 변환한다.

    입력:
        canvases — extract_iiif_canvases()가 반환한 목록.
        dest_dir — 임시 저장 디렉토리.
        label — 출력 PDF 파일명.
        progress_callback — (current_page, total_pages) 콜백.
        max_dimension — 이미지 최대 변(장변) 픽셀.
            None이면 full 크기, 정수면 IIIF Image API !{w},{h} 사용.
            기본 1500px — OCR에 충분하고 다운로드 시간을 합리적으로 유지.
    출력:
        생성된 PDF 파일 Path.
    에러:
        ValueError — 다운로드에 성공한 페이지가 0건일 때.

    왜 이렇게 하는가:
        archives_jp.py의 JPEG→PDF 변환 패턴을 그대로 사용한다.
        fpdf2 + PIL로 이미지를 PDF 페이지로 변환한다.
        개별 페이지 실패 시 건너뛰고 계속 진행한다 (경고 로그만 남김).
    """
    from fpdf import FPDF
    from PIL import Image

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    total = len(canvases)

    # 개별 이미지 다운로드
    jpeg_paths: list[Path] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i, canvas in enumerate(canvases):
            image_url = canvas["image_url"]

            # 이미지 크기 조정
            if max_dimension is not None:
                image_url = _resize_iiif_url(image_url, max_dimension)

            try:
                resp = await client.get(image_url)
                resp.raise_for_status()

                jpeg_path = dest_dir / f"iiif_p{i + 1:04d}.jpg"
                jpeg_path.write_bytes(resp.content)
                jpeg_paths.append(jpeg_path)
            except Exception as e:
                logger.warning("IIIF 이미지 다운로드 실패 (p.%d/%d): %s", i + 1, total, e)
                # 개별 페이지 실패 → 건너뛰기, 전체 중단하지 않음

            if progress_callback:
                progress_callback(i + 1, total)

            # 속도 제한 방지: 페이지 간 0.1초 대기
            if i < total - 1:
                await asyncio.sleep(0.1)

    if not jpeg_paths:
        raise ValueError(
            "IIIF 이미지를 하나도 다운로드하지 못했습니다.\n"
            "→ 해결: 네트워크 연결 상태 또는 URL을 확인하세요."
        )

    # JPEG → PDF 변환 (archives_jp.py 패턴 사용)
    pdf = FPDF(unit="pt")
    for jpeg_path in jpeg_paths:
        with Image.open(jpeg_path) as img:
            # RGBA/P 등 → RGB 변환 (fpdf2 호환)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
                jpeg_path_rgb = jpeg_path.with_suffix(".rgb.jpg")
                img.save(jpeg_path_rgb, "JPEG")
                jpeg_path = jpeg_path_rgb

            w_px, h_px = img.size

        # 150dpi 기준으로 pt 변환 (고서 스캔 해상도)
        w_pt = w_px * 72 / 150
        h_pt = h_px * 72 / 150
        pdf.add_page(format=(w_pt, h_pt))
        pdf.image(str(jpeg_path), x=0, y=0, w=w_pt, h=h_pt)

    safe_label = _sanitize_filename(label)
    pdf_path = dest_dir / f"{safe_label}.pdf"
    pdf.output(str(pdf_path))

    logger.info(
        "IIIF PDF 생성 완료: %s (%d/%d 페이지, %.1fMB)",
        pdf_path.name,
        len(jpeg_paths),
        total,
        pdf_path.stat().st_size / 1024 / 1024,
    )

    return pdf_path
