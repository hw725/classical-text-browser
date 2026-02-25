"""NDL古典籍OCR-Lite OCR 엔진.

일본 국립국회도서관(NDL)의 ndlkotenocr-lite를 래핑한 오프라인 OCR 엔진.
RTMDet(레이아웃/행 탐지) + PARSeq(문자 인식) + XY-Cut(읽기순서)로 구성.

ndlocr-lite(일반)와의 차이:
  - RTMDet 사용 (DEIM 대신) — 1280×1280 입력, 16개 클래스
  - 단일 PARSeq 모델 (캐스케이드 없음) — 고전적 전용 학습
  - 고전적(古典籍) 전용 문자셋 (변체가나·고서체·한문)

지원 언어: 한문(CJK 한자), 일본어 고전적.
한글은 학습 데이터에 포함되지 않아 인식 불가.
국한문(한자+한글 혼용) 문헌에서는 한글 부분이 깨진다.

원본: https://github.com/ndl-lab/ndlkotenocr-lite
라이선스: CC BY 4.0 (National Diet Library, Japan)

의존성 (선택 설치):
  uv sync --extra ndlocr  (또는 --extra ndlkotenocr)
  → onnxruntime, networkx, ordered-set, tqdm
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
# ndlkotenocr RTMDet 모델이 탐지하는 16개 클래스를
# 이 프로젝트의 block_type (resources/block_types.json)으로 매핑.
# ndlocr의 NDLOCR_TO_BLOCK_TYPE과 동일한 패턴이지만 16개 클래스.
NDLKOTENOCR_TO_BLOCK_TYPE = {
    0: "main_text",       # text_block (본문 블록 컨테이너)
    1: "main_text",       # line_main (본문 행)
    2: "annotation",      # line_caption (캡션 행)
    3: "unknown",         # line_ad (광고 — 고전적에서 드묾)
    4: "annotation",      # line_note (割注, 쌍행주)
    5: "marginal_note",   # line_note_tochu (頭注, 두주)
    6: "illustration",    # block_fig (도판)
    7: "unknown",         # block_ad (광고 블록)
    8: "page_title",      # block_pillar (柱, 판심제)
    9: "page_number",     # block_folio (ノンブル, 장차)
    10: "unknown",        # block_rubi (루비)
    11: "illustration",   # block_chart (도표)
    12: "unknown",        # block_eqn (수식)
    13: "unknown",        # block_cfm (확인필요)
    14: "unknown",        # block_eng (영문 블록)
    15: "illustration",   # block_table (표)
}

# LINE 유형의 class_index 집합 (행 단위로 PARSeq 인식 대상)
# ndlocr은 {1, 2, 3, 4, 5, 16}이지만, ndlkotenocr은 16번 없음 (16개 클래스)
_LINE_CLASS_INDICES = {1, 2, 3, 4, 5}


class NdlkotenOcrEngine(BaseOcrEngine):
    """NDL古典籍OCR-Lite 기반 오프라인 OCR 엔진.

    특징:
      - ONNX Runtime 기반 → Python 3.10+ 호환 (3.13 포함)
      - 고전적(古典籍) 전용 학습 모델
      - 페이지 단위 인식 지원 (supports_page_level=True)
      - 레이아웃 탐지 기능 내장 (16개 클래스)

    제한:
      - 한문(CJK 한자)/일본어 고전적만 지원. 한글 인식 불가.
      - 모델 파일(~74MB)이 필요. 첫 사용 시 자동 다운로드.
      - RTMDet 모델이 실제로 다중 클래스를 구분하는지는 모델 의존적.
    """

    engine_id = "ndlkotenocr"
    display_name = "NDL古典籍OCR-Lite (오프라인·고전적 전용)"
    requires_network = False
    supports_page_level = True
    supports_layout_detection = True

    def __init__(self):
        """엔진 초기화. 모델은 첫 사용 시 lazy 로드."""
        self._rtmdet = None          # RTMDet 레이아웃/행 탐지기
        self._parseq = None          # PARSeq 문자 인식기 (단일 모델)
        self._available: Optional[bool] = None
        self._unavailable_reason: Optional[str] = None

    # ── 공개 인터페이스 ──────────────────────────────────────

    def is_available(self) -> bool:
        """onnxruntime 설치 + ONNX 모델 파일 존재 여부를 확인한다.

        결과를 캐시하여 반복 호출 비용을 줄인다.
        """
        if self._available is not None:
            return self._available

        # 1) onnxruntime 설치 확인
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            self._available = False
            self._unavailable_reason = (
                "onnxruntime이 설치되지 않았습니다. "
                "설치: uv sync --extra ndlocr"
            )
            logger.info(f"NDL古典籍OCR-Lite 사용 불가: {self._unavailable_reason}")
            return False

        # 2) 모델 파일 확인
        from .ndlkotenocr import models_available
        if not models_available():
            # 모델은 없지만 런타임은 있으므로 "사용 가능"으로 표시.
            # 실제 OCR 호출 시 ensure_models()로 자동 다운로드 시도.
            self._available = True
            self._unavailable_reason = None
            logger.info(
                "NDL古典籍OCR-Lite: onnxruntime 설치됨. "
                "모델 파일 미감지 — 첫 OCR 실행 시 자동 다운로드됩니다."
            )
            return True

        self._available = True
        self._unavailable_reason = None
        return True

    def recognize(
        self,
        image_bytes: bytes,
        writing_direction: str = "vertical_rtl",
        language: str = "classical_chinese",
        **kwargs,
    ) -> OcrBlockResult:
        """단일 블록(크롭 이미지)에서 텍스트를 인식한다.

        RTMDet로 블록 내 행을 탐지한 뒤 PARSeq로 각 행을 인식.
        블록 이미지에서는 RTMDet 정확도가 다소 떨어질 수 있다.
        가능하면 recognize_page()를 사용하는 것을 권장.
        """
        if not self.is_available():
            raise OcrEngineUnavailableError(
                self._unavailable_reason or "NDL古典籍OCR-Lite 사용 불가"
            )

        self._init_models()

        # 이미지 로드
        pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        np_image = np.array(pil_image)

        # RTMDet로 행 탐지
        detections = self._rtmdet.detect(np_image)

        # LINE 유형만 필터링
        line_dets = [
            d for d in detections if d["class_index"] in _LINE_CLASS_INDICES
        ]

        if not line_dets:
            # 행이 탐지되지 않으면 이미지 전체를 단일 행으로 간주
            return self._recognize_single_line(np_image)

        # ndl_parser → XML → reading_order로 처리
        lines_with_text = self._process_detections(np_image, detections)

        # OcrBlockResult 구성
        ocr_lines = []
        for line_info in lines_with_text:
            chars = [
                OcrCharResult(char=ch)
                for ch in line_info["text"]
            ]
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
          4. PARSeq로 각 LINE 인식 (단일 모델, 캐스케이드 없음)
          5. 인식된 LINE을 L3 block의 bbox와 공간적으로 매칭
          6. 블록별로 그룹화된 결과 반환

        입력:
          page_image_bytes: 전체 페이지 이미지 (PNG 바이트)
          blocks: L3 레이아웃의 블록 목록
          progress_callback: 진행 상황 콜백

        출력:
          ocr_page.schema.json 호환 딕셔너리 목록.
          각 항목: {"layout_block_id": "p01_b01", "lines": [...]}
        """
        if not self.is_available():
            raise OcrEngineUnavailableError(
                self._unavailable_reason or "NDL古典籍OCR-Lite 사용 불가"
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

        # 2. RTMDet + ndl_parser + XY-Cut + PARSeq
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
        done_count = 0  # skip 제외 처리 완료 카운트 (progress 보고용)
        for block in blocks:
            block_id = block.get("block_id", "unknown")
            skip = block.get("skip", False)

            if skip:
                continue

            matched_lines = block_results.get(block_id, [])

            # OcrLineResult → dict 변환
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
            f"NDL古典籍OCR 페이지 인식 완료: "
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

        RTMDet가 탐지한 영역을 우리 block_type으로 매핑하여 반환.
        RTMDet 모델이 실제로 다중 클래스를 구분하는지는 모델 의존적이다.
        모든 탐지가 class 1(line_main)이더라도 행 위치 기반 읽기 순서를
        제공하므로 유용하다.

        입력:
          page_image_bytes: 전체 페이지 이미지 (PNG/JPEG 바이트)
          page_number: 페이지 번호 (block_id 생성에 사용)
          conf_threshold: 신뢰도 임계값 (0이면 기본값 사용, >0이면 후필터링)

        출력: L3 layout blocks 호환 딕셔너리 목록.
        """
        if not self.is_available():
            raise OcrEngineUnavailableError(
                self._unavailable_reason or "NDL古典籍OCR-Lite 사용 불가"
            )

        self._init_models()

        pil_image = Image.open(io.BytesIO(page_image_bytes)).convert("RGB")
        np_image = np.array(pil_image)

        detections = self._rtmdet.detect(np_image)

        layout_blocks = []
        block_idx = 0

        for det in detections:
            class_index = det["class_index"]
            # LINE 유형은 레이아웃 블록으로 변환하지 않음 (행은 블록 내부)
            if class_index in _LINE_CLASS_INDICES:
                continue

            # conf_threshold > 0이면 후필터링 적용
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
        """엔진 정보 + 지원 언어 경고를 포함한 딕셔너리."""
        info = super().get_info()
        info["supported_languages"] = ["classical_chinese", "classical_japanese"]
        info["language_warning"] = (
            "고전적(古典籍) 한문·일본어 전용입니다. "
            "한글은 인식할 수 없습니다. "
            "근현대 자료에는 NDLOCR-Lite를 사용하세요."
        )
        if self._unavailable_reason:
            info["unavailable_reason"] = self._unavailable_reason
        return info

    # ── 내부 헬퍼 ────────────────────────────────────────────

    def _init_models(self) -> None:
        """RTMDet + PARSeq 모델을 lazy 로드한다.

        모델 파일이 없으면 자동 다운로드를 시도한다.
        RTMDet는 ndlkotenocr 패키지에서,
        PARSeq는 ndlocr 패키지의 클래스를 공유하되 ndlkotenocr 모델/config를 사용.
        """
        # 두 모델이 모두 초기화되었으면 재로딩 불필요
        if self._rtmdet is not None and self._parseq is not None:
            return

        from .ndlkotenocr import ensure_models, get_config_dir

        model_dir = ensure_models(auto_download=True)
        if model_dir is None:
            raise OcrEngineUnavailableError(
                "NDL古典籍OCR-Lite 모델 파일을 찾을 수 없고, 다운로드에도 실패했습니다. "
                "수동 다운로드: https://github.com/ndl-lab/ndlkotenocr-lite/tree/v1.3.1/src/model"
            )

        config_dir = get_config_dir()

        logger.info("NDL古典籍OCR-Lite 모델 로딩 중...")

        from .ndlkotenocr.rtmdet import RTMDet
        # PARSeq 클래스는 ndlocr 패키지에서 공유 (동일한 아키텍처)
        from .ndlocr.parseq import PARSEQ
        from yaml import safe_load

        # RTMDet 레이아웃/행 탐지기 (ndlkotenocr 전용 모델)
        if self._rtmdet is None:
            self._rtmdet = RTMDet(
                model_path=str(model_dir / "rtmdet-s-1280x1280.onnx"),
                class_mapping_path=str(config_dir / "ndl.yaml"),
                score_threshold=0.2,
                conf_threshold=0.25,
                iou_threshold=0.2,
            )

        # PARSeq 문자 인식기 (단일 모델 — 캐스케이드 없음)
        # ndlkotenocr 전용 문자셋(config/NDLmoji.yaml) 사용
        if self._parseq is None:
            char_config = config_dir / "NDLmoji.yaml"
            with open(char_config, encoding="utf-8") as f:
                charobj = safe_load(f)
            charlist = list(charobj["model"]["charset_train"])

            self._parseq = PARSEQ(
                model_path=str(model_dir / "parseq-ndl-32x384-tiny-10.onnx"),
                charlist=charlist,
            )

        logger.info("NDL古典籍OCR-Lite 모델 로딩 완료")

    def _process_detections(
        self, np_image: np.ndarray, detections: list[dict],
    ) -> list[dict]:
        """RTMDet 탐지 결과를 처리하여 텍스트가 포함된 LINE 목록을 반환한다.

        처리 흐름:
          1. ndl_parser로 탐지 결과 → XML 문자열 구성
          2. XY-Cut으로 읽기 순서 결정
          3. 각 LINE을 이미지에서 크롭
          4. PARSeq 단일 모델로 각 LINE 인식 (캐스케이드 없음)

        ndlocr_engine._process_detections()와의 차이:
          - resultobj 구성 시 16개 클래스 (range(16))
          - convert_to_xml_string3 호출 시 use_block_ad=False, score_thr=0.3
          - PARSeq 캐스케이드 없이 단일 모델로 직접 인식

        출력: [{"text": "인식결과", "bbox": [x,y,x2,y2], "order": 0}, ...]
        """
        # ndl_parser와 reading_order는 ndlocr 패키지에서 공유
        from .ndlocr.ndl_parser import convert_to_xml_string3
        from .ndlocr.reading_order.xy_cut.eval import eval_xml

        img_h, img_w = np_image.shape[:2]
        classeslist = list(self._rtmdet.classes.values())

        # ndl_parser가 기대하는 형식으로 변환
        # resultobj[0]: {0: [[x1,y1,x2,y2], ...]}  — text_block 좌표
        # resultobj[1]: {0: [...], 1: [...], ..., 15: [...]}  — 클래스별 탐지
        resultobj = [dict(), dict()]
        resultobj[0][0] = []
        for i in range(16):  # 16개 클래스 (ndlocr은 17개)
            resultobj[1][i] = []

        for det in detections:
            xmin, ymin, xmax, ymax = det["box"]
            conf = det["confidence"]
            cls_idx = det["class_index"]
            # text_block (class 0)은 resultobj[0]에도 추가
            if cls_idx == 0:
                resultobj[0][0].append([xmin, ymin, xmax, ymax])
            # 범위 내 클래스만 추가 (안전 검사)
            if 0 <= cls_idx < 16:
                resultobj[1][cls_idx].append([xmin, ymin, xmax, ymax, conf])

        # XML 구성 (ndlkotenocr 고유 파라미터)
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

        # LINE 크롭 + PARSeq 인식 (단일 모델, 캐스케이드 없음)
        lines_with_text = []
        for idx, lineobj in enumerate(root.findall(".//LINE")):
            xmin = int(lineobj.get("X"))
            ymin = int(lineobj.get("Y"))
            line_w = int(lineobj.get("WIDTH"))
            line_h = int(lineobj.get("HEIGHT"))

            # 이미지에서 행 크롭
            lineimg = np_image[ymin:ymin + line_h, xmin:xmin + line_w, :]
            if lineimg.size == 0:
                continue

            # 단일 PARSeq 모델로 인식 (ndlocr의 캐스케이드와 달리 단일 패스)
            text = self._parseq.read(lineimg) or ""

            lines_with_text.append({
                "text": text,
                "bbox": [xmin, ymin, xmin + line_w, ymin + line_h],
                "order": int(lineobj.get("ORDER", idx)),
            })

        # 읽기 순서로 정렬
        lines_with_text.sort(key=lambda x: x["order"])

        return lines_with_text

    def _recognize_single_line(self, np_image: np.ndarray) -> OcrBlockResult:
        """이미지 전체를 단일 행으로 간주하여 인식한다.

        RTMDet가 행을 탐지하지 못한 경우의 폴백.
        """
        text = self._parseq.read(np_image) or ""
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

        각 LINE의 bbox 중심점이 어떤 block의 bbox 안에 들어가는지로 매칭.
        매칭되지 않는 LINE은 가장 가까운 block에 할당.

        ndlocr_engine._match_lines_to_blocks()와 동일한 로직.

        입력:
          lines: [{"text": str, "bbox": [x1,y1,x2,y2], "order": int}, ...]
          blocks: L3 레이아웃 블록 목록 [{"block_id": str, "bbox": [...], ...}, ...]

        출력:
          {block_id: [line_info, ...], ...}
        """
        result: dict[str, list[dict]] = {}

        # skip 블록 제외한 유효 블록
        valid_blocks = [b for b in blocks if not b.get("skip", False)]

        if not valid_blocks:
            # 블록이 없으면 모든 LINE을 "unmatched" 블록으로
            if lines:
                result["unmatched"] = lines
            return result

        for line in lines:
            lx1, ly1, lx2, ly2 = line["bbox"]
            # LINE의 중심점
            cx = (lx1 + lx2) / 2
            cy = (ly1 + ly2) / 2

            best_block_id = None
            best_overlap = -1

            for block in valid_blocks:
                bbox = block.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue

                bx1, by1, bx2, by2 = bbox

                # 중심점이 블록 내부에 있는지
                if bx1 <= cx <= bx2 and by1 <= cy <= by2:
                    # 내부에 있으면 겹침 영역 계산으로 최적 매칭
                    overlap = self._calc_overlap(line["bbox"], bbox)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_block_id = block.get("block_id")

            if best_block_id is None:
                # 중심점이 어떤 블록에도 안 들어가면 가장 가까운 블록 선택
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
        # bbox 내부이면 거리 0
        dx = max(bx1 - cx, 0, cx - bx2)
        dy = max(by1 - cy, 0, cy - by2)
        return (dx * dx + dy * dy) ** 0.5
