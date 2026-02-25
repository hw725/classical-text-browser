"""NDL古典籍OCR-Lite 벤더링 패키지.

원본: https://github.com/ndl-lab/ndlkotenocr-lite
라이선스: CC BY 4.0 (National Diet Library, Japan)

이 패키지는 ndlkotenocr-lite의 핵심 소스를 벤더링한 것이다.
ONNX 모델 파일(~74MB)은 첫 사용 시 GitHub에서 자동 다운로드된다.

ndlocr-lite(일반)와의 차이:
  - RTMDet 레이아웃 탐지기 (DEIM 대신)
  - 단일 PARSeq 모델 (캐스케이드 없음)
  - 고전적(古典籍) 전용 학습 데이터 (みんなで翻刻 + NDL)
  - 16개 클래스 (ndlocr은 17개)

지원 언어: 한문(CJK 한자), 일본어 고전적(変体仮名·古書体).
한글은 학습 데이터에 포함되지 않아 인식 불가.
"""

from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 모델 파일 관리 ──────────────────────────────────────

# 모델 캐시 디렉토리 (ndlocr과 분리)
_DEFAULT_MODEL_DIR = Path.home() / ".cache" / "classical-text-browser" / "ndlkotenocr-models"

# GitHub 안정 릴리즈 태그에서 모델 다운로드 (raw URL)
# master가 아닌 v1.3.1 태그를 고정하여 재현성을 보장한다.
_GITHUB_RAW_BASE = (
    "https://github.com/ndl-lab/ndlkotenocr-lite/raw/v1.3.1/src/model/"
)

# 필요한 ONNX 모델 파일 목록 (2개, 총 ~74MB)
MODEL_FILES = [
    "rtmdet-s-1280x1280.onnx",          # ~38.3 MB — RTMDet 레이아웃/행 탐지
    "parseq-ndl-32x384-tiny-10.onnx",    # ~36.0 MB — PARSeq 고전적 문자 인식
]


def get_model_dir() -> Path:
    """ONNX 모델 디렉토리 경로를 반환한다.

    우선순위:
      1. 환경변수 NDLKOTENOCR_MODEL_PATH (사용자가 직접 지정)
      2. 기본 캐시 디렉토리 (~/.cache/classical-text-browser/ndlkotenocr-models/)
    """
    env_path = os.environ.get("NDLKOTENOCR_MODEL_PATH")
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
            f"NDL古典籍OCR-Lite 모델 파일이 없습니다: {model_dir}\n"
            f"설치 방법: 환경변수 NDLKOTENOCR_MODEL_PATH를 설정하거나, "
            f"자동 다운로드를 허용하세요."
        )
        return None

    # 자동 다운로드 시도
    logger.info(f"NDL古典籍OCR-Lite 모델 다운로드 시작 → {model_dir}")
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
        logger.info("NDL古典籍OCR-Lite 모델 다운로드 완료")
        return model_dir
    else:
        logger.error("일부 모델 다운로드 실패. 수동 다운로드 필요.")
        return None


def get_config_dir() -> Path:
    """config 디렉토리 경로를 반환한다 (ndl.yaml, NDLmoji.yaml 위치)."""
    return Path(__file__).parent / "config"
