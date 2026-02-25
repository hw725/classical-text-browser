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
# master가 아닌 1.3.1 태그를 고정하여 재현성을 보장한다.
# 주의: 이 저장소의 태그에는 'v' 접두사가 없다 (v1.3.1 ✗ → 1.3.1 ✓).
_GITHUB_RAW_BASE = (
    "https://raw.githubusercontent.com/ndl-lab/ndlkotenocr-lite/1.3.1/src/model/"
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


# ── Full 모델 (TrOCR) 파일 관리 ──────────────────────────
#
# NDL古典籍OCR 풀 버전(ndlkotenocr_cli)의 TrOCR 문자 인식 모델.
# HuggingFace VisionEncoderDecoderModel 형식, PyTorch 기반.
# RTMDet ONNX(lite)와 조합하여 하이브리드 엔진으로 사용.
#
# 원본: https://github.com/ndl-lab/ndlkotenocr_cli (ver.3)
# 다운로드: https://lab.ndl.go.jp/dataset/ndlkotensekiocr/trocr/model-ver2.zip

_DEFAULT_FULL_MODEL_DIR = (
    Path.home() / ".cache" / "classical-text-browser" / "ndlkotenocr-full-models"
)
_FULL_MODEL_URL = "https://lab.ndl.go.jp/dataset/ndlkotensekiocr/trocr/model-ver2.zip"

# zip 해제 후 3개 서브디렉토리가 필요
FULL_MODEL_SUBDIRS = [
    "model-ver2/trocr-base-preprocessor",       # TrOCRProcessor (전처리)
    "model-ver2/decoder-roberta-v3",             # AutoTokenizer (디코더)
    "model-ver2/kotenseki-trocr-honkoku-ver2",   # VisionEncoderDecoderModel (본체)
]


def get_full_model_dir() -> Path:
    """TrOCR 풀 모델 디렉토리 경로를 반환한다.

    우선순위:
      1. 환경변수 NDLKOTENOCR_FULL_MODEL_PATH (사용자가 직접 지정)
      2. 기본 캐시 디렉토리 (~/.cache/classical-text-browser/ndlkotenocr-full-models/)
    """
    env_path = os.environ.get("NDLKOTENOCR_FULL_MODEL_PATH")
    if env_path:
        return Path(env_path)
    return _DEFAULT_FULL_MODEL_DIR


def full_models_available() -> bool:
    """TrOCR 모델 3개 서브디렉토리가 모두 존재하는지 확인한다."""
    model_dir = get_full_model_dir()
    return all((model_dir / sub).is_dir() for sub in FULL_MODEL_SUBDIRS)


def ensure_full_models(auto_download: bool = True) -> Optional[Path]:
    """TrOCR 풀 모델을 확인하고, 없으면 zip 다운로드+해제한다.

    NDL 공식 서버에서 model-ver2.zip (~1GB)을 다운로드하여
    3개 서브디렉토리(preprocessor, tokenizer, model)로 해제한다.

    입력:
      auto_download: True이면 모델이 없을 때 자동 다운로드 시도.

    출력:
      모델 디렉토리 경로 (성공 시), None (실패 시)
    """
    model_dir = get_full_model_dir()

    if full_models_available():
        return model_dir

    if not auto_download:
        logger.warning(
            f"NDL古典籍OCR Full(TrOCR) 모델 파일이 없습니다: {model_dir}\n"
            f"설치 방법:\n"
            f"  1. 자동 다운로드: 서버 시작 시 자동 다운로드됩니다.\n"
            f"  2. 수동 다운로드:\n"
            f"     wget {_FULL_MODEL_URL}\n"
            f"     unzip model-ver2.zip -d {model_dir}\n"
            f"  3. 환경변수: NDLKOTENOCR_FULL_MODEL_PATH=<모델 디렉토리>"
        )
        return None

    # 자동 다운로드 시도
    logger.info(f"NDL古典籍OCR Full(TrOCR) 모델 다운로드 시작 → {model_dir}")
    model_dir.mkdir(parents=True, exist_ok=True)

    try:
        import httpx
    except ImportError:
        logger.error("httpx가 설치되지 않아 모델 다운로드 불가")
        return None

    zip_path = model_dir / "model-ver2.zip"

    try:
        # 1. zip 다운로드 (대용량이므로 스트리밍)
        logger.info(f"  다운로드 중: model-ver2.zip ({_FULL_MODEL_URL})")
        with httpx.stream(
            "GET", _FULL_MODEL_URL, follow_redirects=True, timeout=600.0,
        ) as resp:
            resp.raise_for_status()
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with open(zip_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = downloaded * 100 / total_size
                        # 10% 단위로 로그
                        if int(pct) % 10 == 0 and int(pct) > 0:
                            logger.info(
                                f"  다운로드 진행: {downloaded / 1024 / 1024:.0f}MB "
                                f"/ {total_size / 1024 / 1024:.0f}MB ({pct:.0f}%)"
                            )

        zip_size = zip_path.stat().st_size
        logger.info(f"  다운로드 완료: {zip_size / 1024 / 1024:.1f} MB")

        # 2. zip 해제
        import zipfile

        logger.info("  압축 해제 중...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(model_dir)
        logger.info("  압축 해제 완료")

        # 3. zip 파일 삭제 (공간 절약)
        zip_path.unlink()
        logger.info("  임시 zip 파일 삭제됨")

    except Exception as e:
        logger.error(f"  TrOCR 모델 다운로드 실패: {e}")
        # 불완전한 zip 삭제
        if zip_path.exists():
            zip_path.unlink()
        return None

    # 4. 모든 서브디렉토리가 생성되었는지 확인
    if full_models_available():
        logger.info("NDL古典籍OCR Full(TrOCR) 모델 다운로드 완료")
        return model_dir
    else:
        missing = [
            sub for sub in FULL_MODEL_SUBDIRS
            if not (model_dir / sub).is_dir()
        ]
        logger.error(
            f"zip 해제 후 일부 디렉토리 누락: {missing}\n"
            f"수동으로 {_FULL_MODEL_URL} 을 다운로드하여 {model_dir}에 해제하세요."
        )
        return None
