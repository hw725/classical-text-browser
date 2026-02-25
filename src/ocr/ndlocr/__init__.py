"""NDLOCR-Lite 벤더링 패키지.

원본: https://github.com/ndl-lab/ndlocr-lite
라이선스: CC BY 4.0 (National Diet Library, Japan)

이 패키지는 ndlocr-lite의 핵심 소스를 벤더링한 것이다.
ONNX 모델 파일(~147MB)은 첫 사용 시 GitHub에서 자동 다운로드된다.

지원 언어: 한문(CJK 한자), 일본어. 한글은 인식 불가.
"""

from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 모델 파일 관리 ──────────────────────────────────────

# 모델 캐시 디렉토리
_DEFAULT_MODEL_DIR = Path.home() / ".cache" / "classical-text-browser" / "ndlocr-models"

# GitHub 원본 저장소에서 모델 다운로드 (raw URL)
_GITHUB_RAW_BASE = "https://github.com/ndl-lab/ndlocr-lite/raw/master/src/model/"

# 필요한 ONNX 모델 파일 목록
MODEL_FILES = [
    "deim-s-1024x1024.onnx",
    "parseq-ndl-16x256-30-tiny-192epoch-tegaki3.onnx",
    "parseq-ndl-16x384-50-tiny-146epoch-tegaki2.onnx",
    "parseq-ndl-16x768-100-tiny-165epoch-tegaki2.onnx",
]


def get_model_dir() -> Path:
    """ONNX 모델 디렉토리 경로를 반환한다.

    우선순위:
      1. 환경변수 NDLOCR_MODEL_PATH (사용자가 직접 지정)
      2. 기본 캐시 디렉토리 (~/.cache/classical-text-browser/ndlocr-models/)
    """
    env_path = os.environ.get("NDLOCR_MODEL_PATH")
    if env_path:
        return Path(env_path)
    return _DEFAULT_MODEL_DIR


def models_available() -> bool:
    """모든 ONNX 모델 파일이 존재하는지 확인한다."""
    model_dir = get_model_dir()
    return all((model_dir / fname).exists() for fname in MODEL_FILES)


def ensure_models(auto_download: bool = True) -> Optional[Path]:
    """모델 파일을 확인하고, 없으면 다운로드한다.

    입력:
      auto_download: True이면 모델이 없을 때 자동 다운로드 시도.

    출력:
      모델 디렉토리 경로 (성공 시), None (실패 시)
    """
    model_dir = get_model_dir()

    if models_available():
        return model_dir

    if not auto_download:
        logger.warning(
            f"NDLOCR-Lite 모델 파일이 없습니다: {model_dir}\n"
            f"설치 방법: 환경변수 NDLOCR_MODEL_PATH를 설정하거나, "
            f"자동 다운로드를 허용하세요."
        )
        return None

    # 자동 다운로드 시도
    logger.info(f"NDLOCR-Lite 모델 다운로드 시작 → {model_dir}")
    model_dir.mkdir(parents=True, exist_ok=True)

    try:
        import httpx
    except ImportError:
        logger.error("httpx가 설치되지 않아 모델 다운로드 불가")
        return None

    all_ok = True
    for fname in MODEL_FILES:
        target = model_dir / fname
        if target.exists():
            logger.info(f"  이미 존재: {fname}")
            continue

        url = _GITHUB_RAW_BASE + fname
        logger.info(f"  다운로드 중: {fname} ({url})")
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as resp:
                resp.raise_for_status()
                with open(target, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        f.write(chunk)
            logger.info(f"  완료: {fname} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
        except Exception as e:
            logger.error(f"  다운로드 실패: {fname} — {e}")
            # 불완전한 파일 삭제
            if target.exists():
                target.unlink()
            all_ok = False

    if all_ok:
        logger.info("NDLOCR-Lite 모델 다운로드 완료")
        return model_dir
    else:
        logger.error("일부 모델 다운로드 실패. 수동 다운로드 필요.")
        return None


def get_config_dir() -> Path:
    """config 디렉토리 경로를 반환한다 (ndl.yaml, NDLmoji.yaml 위치)."""
    return Path(__file__).parent / "config"
