"""NDL古典籍OCR Full (TrOCR) OCR 엔진.

RTMDet ONNX(lite) + TrOCR PyTorch(full) 하이브리드 엔진.
RTMDet로 레이아웃/행을 탐지하고, TrOCR로 문자를 인식한다.

ndlkotenocr_engine.py(lite)와의 차이:
  - 문자 인식: PARSeq-tiny ONNX (~37MB) → TrOCR PyTorch (~1GB)
  - 레이아웃 탐지: RTMDet ONNX 동일 (lite 모델 공유)
  - 읽기 순서: XY-Cut 동일 (ndlocr 공유)
  - GPU 권장: TrOCR는 CPU에서도 동작하나 행당 2-5초로 느림

모델:
  - RTMDet: ndlkotenocr-lite의 rtmdet-s-1280x1280.onnx (~38MB, 공유)
  - TrOCR: ndlkotenocr_cli의 model-ver2/ (~1GB, 별도 다운로드)
    - trocr-base-preprocessor/
    - decoder-roberta-v3/
    - kotenseki-trocr-honkoku-ver2/

의존성 (선택 설치):
  uv sync --extra ndlkotenocr-full
  → torch>=2.6.0, torchvision>=0.21.0, transformers>=4.47.0, onnxruntime>=1.20.0

원본: https://github.com/ndl-lab/ndlkotenocr_cli (CC BY 4.0)
"""

from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
from typing import Callable, Optional

import numpy as np
from PIL import Image

from .base import (
    BaseOcrEngine,
    OcrBlockResult,
    OcrCharResult,
    OcrEngineUnavailableError,
    OcrLineResult,
)

logger = logging.getLogger(__name__)


# ── ndlkotenocr 카테고리 → 우리 block_type 매핑 ────────────
# ndlkotenocr_engine.py(lite)와 동일한 매핑.
# 두 엔진 모두 RTMDet 16개 클래스를 사용하므로 매핑 공유.
NDLKOTENOCR_TO_BLOCK_TYPE = {
    0: "main_text",       # text_block
    1: "main_text",       # line_main
    2: "annotation",      # line_caption
    3: "unknown",         # line_ad
    4: "annotation",      # line_note
    5: "marginal_note",   # line_note_tochu
    6: "illustration",    # block_fig
    7: "unknown",         # block_ad
    8: "page_title",      # block_pillar (柱)
    9: "page_number",     # block_folio (ノンブル)
    10: "unknown",        # block_rubi
    11: "illustration",   # block_chart
    12: "unknown",        # block_eqn
    13: "unknown",        # block_cfm
    14: "unknown",        # block_eng
    15: "illustration",   # block_table
}

# LINE 유형의 class_index 집합 (행 단위로 TrOCR 인식 대상)
_LINE_CLASS_INDICES = {1, 2, 3, 4, 5}


class NdlkotenOcrFullEngine(BaseOcrEngine):
    """NDL古典籍OCR Full (TrOCR) 기반 오프라인 OCR 엔진.

    특징:
      - RTMDet ONNX(lite 공유) + TrOCR PyTorch(full) 하이브리드
      - TrOCR는 PARSeq-tiny보다 인식 품질이 높음 (특히 변체가나·고서체)
      - 배치 인식 지원 (GPU에서 전체 페이지 LINE을 한 번에 처리)
      - CUDA GPU 권장 (CPU도 동작하나 느림)

    제한:
      - torch + transformers 설치 필요 (~4GB with CUDA)
      - TrOCR 모델 파일(~1GB) 별도 다운로드 필요
      - CPU에서는 행당 2-5초 (20행 페이지 ≈ 1분)
      - 한문(CJK 한자)/일본어 고전적만 지원. 한글 인식 불가.
    """

    engine_id = "ndlkotenocr-full"
    display_name = "NDL古典籍OCR Full (TrOCR·고전적 전용)"
    requires_network = False
    supports_page_level = True
    supports_layout_detection = True

    def __init__(self):
        """엔진 초기화. 모델은 첫 사용 시 lazy 로드."""
        self._rtmdet = None          # RTMDet 레이아웃/행 탐지기 (lite 공유)
        self._trocr = None           # TrOCR 문자 인식기 (full)
        self._available: Optional[bool] = None
        self._unavailable_reason: Optional[str] = None

    # ── 공개 인터페이스 ──────────────────────────────────────

    def is_available(self) -> bool:
        """torch + transformers + onnxruntime 설치 + 모델 파일 존재 확인.

        결과를 캐시하여 반복 호출 비용을 줄인다.
        """
        if self._available is not None:
            return self._available

        # 1) torch 설치 확인
        try:
            import torch  # noqa: F401
        except ImportError:
            self._available = False
            self._unavailable_reason = (
                "torch가 설치되지 않았습니다. "
                "설치: uv sync --extra ndlkotenocr-full"
            )
            logger.debug(f"NDL古典籍OCR Full 사용 불가: {self._unavailable_reason}")
            return False

        # 2) transformers 설치 확인
        try:
            import transformers  # noqa: F401
        except ImportError:
            self._available = False
            self._unavailable_reason = (
                "transformers가 설치되지 않았습니다. "
                "설치: uv sync --extra ndlkotenocr-full"
            )
            logger.debug(f"NDL古典籍OCR Full 사용 불가: {self._unavailable_reason}")
            return False

        # 3) onnxruntime 설치 확인 (RTMDet ONNX용)
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            self._available = False
            self._unavailable_reason = (
                "onnxruntime이 설치되지 않았습니다. "
                "설치: uv sync --extra ndlkotenocr-full"
            )
            logger.debug(f"NDL古典籍OCR Full 사용 불가: {self._unavailable_reason}")
            return False

        # 모든 런타임이 설치됨 → "사용 가능"으로 표시.
        # 모델 파일은 첫 OCR 호출 시 자동 다운로드.
        self._available = True
        self._unavailable_reason = None

        import torch
        device_info = "CUDA" if torch.cuda.is_available() else "CPU"
        logger.info(
            f"NDL古典籍OCR Full: torch + transformers 설치됨 (device: {device_info}). "
            f"모델 파일은 첫 OCR 실행 시 확인/다운로드됩니다."
        )
        return True

    def recognize(
        self,
        image_bytes: bytes,
        writing_direction: str = "vertical_rtl",
        language: str = "classical_chinese",
        **kwargs,
    ) -> OcrBlockResult:
        """단일 블록(크롭 이미지)에서 텍스트를 인식한다.

        RTMDet로 블록 내 행을 탐지한 뒤 TrOCR로 각 행을 인식.
        가능하면 recognize_page()를 사용하는 것을 권장 (배치 처리 효율).
        """
        if not self.is_available():
            raise OcrEngineUnavailableError(
                self._unavailable_reason or "NDL古典籍OCR Full 사용 불가"
            )

        self._init_models()

        # 이미지 로드
        pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        np_image = np.array(pil_image)

        # RTMDet로 행 탐지
        detections = self._rtmdet.detect(np_image)

        if not detections:
            return self._recognize_single_line(np_image)

        # ndl_parser → XML → reading_order → TrOCR 인식
        lines_with_text = self._process_detections(np_image, detections)

        # OcrBlockResult 구성
        ocr_lines = []
        for line_info in lines_with_text:
            chars = [OcrCharResult(char=ch) for ch in line_info["text"]]
            ocr_lines.append(OcrLineResult(
                text=line_info["text"],
                bbox=line_info.get("bbox"),
                characters=chars,
            ))

        return OcrBlockResult(
            lines=ocr_lines,
            engine_id=self.engine_id,
            language=language,
            writing_direction=writing_direction,
        )

    def recognize_page(
        self,
        page_image_bytes: bytes,
        blocks: list[dict],
        progress_callback: Optional[Callable] = None,
        **kwargs,
    ) -> list[dict]:
        """페이지 전체를 한 번에 인식한다 (권장 경로).

        처리 흐름:
          1. RTMDet로 전체 페이지에서 LINE 탐지
          2. ndl_parser로 XML 구성
          3. XY-Cut으로 읽기 순서 결정
          4. TrOCR 배치 인식 (GPU 활용 극대화)
          5. 인식된 LINE을 L3 block의 bbox와 공간적으로 매칭
          6. 블록별로 그룹화된 결과 반환
        """
        if not self.is_available():
            raise OcrEngineUnavailableError(
                self._unavailable_reason or "NDL古典籍OCR Full 사용 불가"
            )

        self._init_models()

        # 1. 이미지 로드
        pil_image = Image.open(io.BytesIO(page_image_bytes)).convert("RGB")
        np_image = np.array(pil_image)

        # 진행 콜백: 시작
        processable = [b for b in blocks if not b.get("skip", False)]
        total = len(processable)

        if progress_callback:
            progress_callback({
                "current": 0, "total": total,
                "block_id": "", "status": "detecting_lines",
            })

        # 2. RTMDet + ndl_parser + XY-Cut + TrOCR (배치)
        lines_with_text = self._process_detections(
            np_image, self._rtmdet.detect(np_image),
        )

        if progress_callback:
            progress_callback({
                "current": 0, "total": total,
                "block_id": "", "status": "matching_blocks",
            })

        # 3. LINE → L3 block 매칭
        block_results = self._match_lines_to_blocks(lines_with_text, blocks)

        # 4. 결과 구성
        results = []
        done_count = 0
        for block in blocks:
            block_id = block.get("block_id", "unknown")
            skip = block.get("skip", False)

            if skip:
                continue

            matched_lines = block_results.get(block_id, [])

            line_dicts = []
            for line_info in matched_lines:
                chars = [
                    OcrCharResult(char=ch).to_dict()
                    for ch in line_info["text"]
                ]
                line_dict = {"text": line_info["text"]}
                if line_info.get("bbox"):
                    line_dict["bbox"] = [round(v, 2) for v in line_info["bbox"]]
                if chars:
                    line_dict["characters"] = chars
                line_dicts.append(line_dict)

            results.append({
                "layout_block_id": block_id,
                "lines": line_dicts,
            })

            done_count += 1
            if progress_callback:
                progress_callback({
                    "current": done_count, "total": total,
                    "block_id": block_id, "status": "processing",
                })

        logger.info(
            f"NDL古典籍OCR Full 페이지 인식 완료: "
            f"{len(lines_with_text)}행 탐지 → {len(results)}블록에 매칭"
        )
        return results

    def detect_layout(
        self,
        page_image_bytes: bytes,
        page_number: int = 1,
        conf_threshold: float = 0.0,
    ) -> list[dict]:
        """레이아웃만 탐지한다 (OCR 없이).

        RTMDet가 탐지한 영역의 실제 class_id를 사용하여 block_type으로 매핑.
        LINE 유형(class 1~5)은 제외하고, BLOCK 유형(class 0, 6~15)만 반환.

        lite 엔진의 detect_layout()과 동일한 RTMDet 모델을 사용하므로
        결과도 동일하다.
        """
        if not self.is_available():
            raise OcrEngineUnavailableError(
                self._unavailable_reason or "NDL古典籍OCR Full 사용 불가"
            )

        self._init_models()

        pil_image = Image.open(io.BytesIO(page_image_bytes)).convert("RGB")
        np_image = np.array(pil_image)

        detections = self._rtmdet.detect(np_image)

        layout_blocks = []
        block_idx = 0

        for det in detections:
            class_index = det["class_index"]
            if class_index in _LINE_CLASS_INDICES:
                continue

            det_conf = float(det.get("confidence", 0))
            if conf_threshold > 0 and det_conf < conf_threshold:
                continue

            x1, y1, x2, y2 = det["box"]
            block_type = NDLKOTENOCR_TO_BLOCK_TYPE.get(class_index, "unknown")

            layout_blocks.append({
                "block_id": f"p{page_number:02d}_b{block_idx + 1:02d}",
                "block_type": block_type,
                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                "reading_order": block_idx,
                "writing_direction": "vertical_rtl",
                "confidence": det_conf,
                "skip": block_type in ("illustration", "page_number"),
            })
            block_idx += 1

        return layout_blocks

    def get_info(self) -> dict:
        """엔진 정보 + 지원 언어 경고 + device 정보를 포함한 딕셔너리."""
        info = super().get_info()
        info["supported_languages"] = ["classical_chinese", "classical_japanese"]
        info["language_warning"] = (
            "고전적(古典籍) 한문·일본어 전용입니다. "
            "한글은 인식할 수 없습니다. "
            "근현대 자료에는 NDLOCR-Lite를 사용하세요."
        )
        info["model_type"] = "TrOCR (HuggingFace VisionEncoderDecoder)"
        info["layout_model"] = "RTMDet ONNX (lite 공유)"

        # device 정보 추가
        try:
            import torch
            info["device"] = "cuda" if torch.cuda.is_available() else "cpu"
            if torch.cuda.is_available():
                info["gpu_name"] = torch.cuda.get_device_name(0)
        except ImportError:
            info["device"] = "unknown"

        if self._unavailable_reason:
            info["unavailable_reason"] = self._unavailable_reason
        return info

    # ── 내부 헬퍼 ────────────────────────────────────────────

    def _init_models(self) -> None:
        """RTMDet ONNX(lite 공유) + TrOCR PyTorch(full) 모델을 lazy 로드한다.

        RTMDet: ndlkotenocr-lite의 모델을 그대로 사용.
        TrOCR: ndlkotenocr_cli의 model-ver2 사용.
        두 모델 세트를 독립적으로 다운로드/관리한다.
        """
        if self._rtmdet is not None and self._trocr is not None:
            return

        # ── RTMDet (lite 모델 공유) ──
        if self._rtmdet is None:
            from .ndlkotenocr import ensure_models, get_config_dir

            lite_model_dir = ensure_models(auto_download=True)
            if lite_model_dir is None:
                raise OcrEngineUnavailableError(
                    "RTMDet ONNX 모델 파일을 찾을 수 없고, 다운로드에도 실패했습니다. "
                    "수동 다운로드: https://github.com/ndl-lab/ndlkotenocr-lite/"
                    "tree/1.3.1/src/model"
                )

            config_dir = get_config_dir()

            from .ndlkotenocr.rtmdet import RTMDet

            self._rtmdet = RTMDet(
                model_path=str(lite_model_dir / "rtmdet-s-1280x1280.onnx"),
                class_mapping_path=str(config_dir / "ndl.yaml"),
                score_threshold=0.3,
                conf_threshold=0.3,
                iou_threshold=0.3,
            )
            logger.info("RTMDet ONNX 모델 로딩 완료 (lite 공유)")

        # ── TrOCR (full 모델) ──
        if self._trocr is None:
            from .ndlkotenocr import ensure_full_models, get_full_model_dir

            full_model_dir = ensure_full_models(auto_download=True)
            if full_model_dir is None:
                raise OcrEngineUnavailableError(
                    "TrOCR 모델 파일을 찾을 수 없고, 다운로드에도 실패했습니다. "
                    "수동 다운로드:\n"
                    "  wget https://lab.ndl.go.jp/dataset/ndlkotensekiocr/trocr/"
                    "model-ver2.zip\n"
                    f"  unzip model-ver2.zip -d {get_full_model_dir()}"
                )

            from .ndlkotenocr.trocr import TrOCRRecognizer

            self._trocr = TrOCRRecognizer(
                preprocessor_path=str(
                    full_model_dir / "model-ver2" / "trocr-base-preprocessor"
                ),
                tokenizer_path=str(
                    full_model_dir / "model-ver2" / "decoder-roberta-v3"
                ),
                model_path=str(
                    full_model_dir / "model-ver2" / "kotenseki-trocr-honkoku-ver2"
                ),
                device="auto",
                batch_size=16,
            )

    def _process_detections(
        self, np_image: np.ndarray, detections: list[dict],
    ) -> list[dict]:
        """RTMDet 탐지 결과를 처리하여 텍스트가 포함된 LINE 목록을 반환한다.

        처리 흐름:
          1. ndl_parser로 탐지 결과 → XML 문자열 구성
          2. XY-Cut으로 읽기 순서 결정
          3. 각 LINE을 이미지에서 크롭
          4. TrOCR 배치 인식 (GPU 활용 극대화)

        ★ 업스트림 호환성: lite 엔진과 동일하게 모든 탐지를 class 1로 취급 ★
        """
        from .ndlocr.ndl_parser import convert_to_xml_string3
        from .ndlocr.reading_order.xy_cut.eval import eval_xml

        img_h, img_w = np_image.shape[:2]
        classeslist = list(self._rtmdet.classes.values())

        # ndl_parser 형식 구성
        resultobj = [dict(), dict()]
        resultobj[0][0] = []
        for i in range(16):
            resultobj[1][i] = []

        # 업스트림 호환: 모든 탐지를 class 1(line_main)로 취급
        for det in detections:
            xmin, ymin, xmax, ymax = det["box"]
            conf = det["confidence"]
            resultobj[1][1].append([xmin, ymin, xmax, ymax, conf])

        # XML 구성
        xmlstr = convert_to_xml_string3(
            img_w, img_h, "page.jpg", classeslist, resultobj,
            use_block_ad=False,
            score_thr=0.3,
            min_bbox_size=5,
        )
        xmlstr = "<OCRDATASET>" + xmlstr + "</OCRDATASET>"
        root = ET.fromstring(xmlstr)

        # XY-Cut 읽기 순서 결정
        eval_xml(root, logger=None)

        # LINE 크롭 수집
        line_crops = []
        line_metadata = []
        for idx, lineobj in enumerate(root.findall(".//LINE")):
            xmin = int(lineobj.get("X"))
            ymin = int(lineobj.get("Y"))
            line_w = int(lineobj.get("WIDTH"))
            line_h = int(lineobj.get("HEIGHT"))

            lineimg = np_image[ymin:ymin + line_h, xmin:xmin + line_w, :]
            if lineimg.size == 0:
                continue

            line_crops.append(lineimg)
            line_metadata.append({
                "bbox": [xmin, ymin, xmin + line_w, ymin + line_h],
                "order": int(lineobj.get("ORDER", idx)),
            })

        # ★ TrOCR 배치 인식 (lite의 개별 PARSeq.read()와 다른 핵심 차이) ★
        # GPU에서 전체 LINE을 한 번에 처리하면 개별 호출 대비 2-5배 빠르다.
        if line_crops:
            texts = self._trocr.read_batch(line_crops)
        else:
            texts = []

        # 결과 조합
        lines_with_text = []
        for text, meta in zip(texts, line_metadata):
            lines_with_text.append({
                "text": text or "",
                "bbox": meta["bbox"],
                "order": meta["order"],
            })

        # 읽기 순서로 정렬
        lines_with_text.sort(key=lambda x: x["order"])

        return lines_with_text

    def _recognize_single_line(self, np_image: np.ndarray) -> OcrBlockResult:
        """이미지 전체를 단일 행으로 간주하여 인식한다.

        RTMDet가 행을 탐지하지 못한 경우의 폴백.
        """
        text = self._trocr.read(np_image) or ""
        chars = [OcrCharResult(char=ch) for ch in text]
        line = OcrLineResult(text=text, characters=chars)
        return OcrBlockResult(
            lines=[line] if text else [],
            engine_id=self.engine_id,
        )

    def _match_lines_to_blocks(
        self,
        lines: list[dict],
        blocks: list[dict],
    ) -> dict[str, list[dict]]:
        """탐지된 LINE을 L3 block에 공간적으로 매칭한다.

        ndlkotenocr_engine.py(lite)의 _match_lines_to_blocks()와 동일한 로직.
        """
        result: dict[str, list[dict]] = {}

        valid_blocks = [b for b in blocks if not b.get("skip", False)]

        if not valid_blocks:
            if lines:
                result["unmatched"] = lines
            return result

        for line in lines:
            lx1, ly1, lx2, ly2 = line["bbox"]
            cx = (lx1 + lx2) / 2
            cy = (ly1 + ly2) / 2

            best_block_id = None
            best_overlap = -1

            for block in valid_blocks:
                bbox = block.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue

                bx1, by1, bx2, by2 = bbox

                if bx1 <= cx <= bx2 and by1 <= cy <= by2:
                    overlap = self._calc_overlap(line["bbox"], bbox)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_block_id = block.get("block_id")

            if best_block_id is None:
                min_dist = float("inf")
                for block in valid_blocks:
                    bbox = block.get("bbox")
                    if not bbox or len(bbox) != 4:
                        continue
                    dist = self._distance_to_bbox(cx, cy, bbox)
                    if dist < min_dist:
                        min_dist = dist
                        best_block_id = block.get("block_id")

            if best_block_id:
                result.setdefault(best_block_id, []).append(line)

        return result

    @staticmethod
    def _calc_overlap(bbox1: list, bbox2: list) -> float:
        """두 bbox의 겹침 비율 (intersection / bbox1 면적)."""
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        area1 = max((bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1]), 1)
        return intersection / area1

    @staticmethod
    def _distance_to_bbox(cx: float, cy: float, bbox: list) -> float:
        """점 (cx, cy)에서 bbox까지의 최소 거리."""
        bx1, by1, bx2, by2 = bbox
        dx = max(bx1 - cx, 0, cx - bx2)
        dy = max(by1 - cy, 0, cy - by2)
        return (dx * dx + dy * dy) ** 0.5