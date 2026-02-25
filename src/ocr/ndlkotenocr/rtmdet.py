"""RTMDet 레이아웃/행 탐지기.

ndlkotenocr-lite의 RTMDet를 벤더링.
원본: https://github.com/ndl-lab/ndlkotenocr-lite/blob/1.3.1/src/rtmdet.py
라이선스: CC BY 4.0 (National Diet Library, Japan)

DEIM (ndlocr-lite)과의 차이:
  - 입력 크기: 1280×1280 (DEIM은 1024×1024)
  - 전처리: BGR + mean=[103.53, 116.28, 123.675], std=[57.375, 57.12, 58.395]
    (DEIM은 RGB + ImageNet mean/std)
  - ONNX 입력: 1개 (이미지만). DEIM은 2개 (이미지 + original_size).
  - ONNX 출력: 2개 (bboxes, class_ids). DEIM은 3-4개.
  - 후처리: 2% 세로 패딩 추가.

업스트림 변경사항:
  업스트림 postprocess()는 모든 탐지의 class_index를 1(line_main)로 하드코딩한다.
  우리 버전은 실제 모델 출력의 class_id를 보존하여 레이아웃 감지에 활용한다.
"""

from PIL import Image, ImageDraw
import yaml
import onnxruntime
import numpy as np
from typing import Tuple, List


class RTMDet:
    """RTMDet 레이아웃/행 탐지기.

    고전적(古典籍) 자료 전용으로 학습된 RTMDet-S 모델을 ONNX로 추론.
    16개 클래스를 탐지한다 (text_block, line_main, block_fig 등).

    사용법:
        detector = RTMDet(
            model_path="rtmdet-s-1280x1280.onnx",
            class_mapping_path="config/ndl.yaml",
        )
        detections = detector.detect(np_image)
        # detections: [{"class_index": int, "confidence": float, "box": [x1,y1,x2,y2], ...}, ...]
    """

    def __init__(
        self,
        model_path: str,
        class_mapping_path: str,
        original_size: Tuple[int, int] = (1280, 1280),
        score_threshold: float = 0.1,
        conf_threshold: float = 0.1,
        iou_threshold: float = 0.4,
        device: str = "CPU",
    ) -> None:
        """RTMDet 초기화.

        입력:
          model_path: ONNX 모델 파일 경로
          class_mapping_path: 클래스 매핑 YAML 파일 경로 (config/ndl.yaml)
          original_size: 모델 입력 크기 (기본 1280×1280)
          score_threshold: 점수 임계값 (NMS 등에 사용, 현재 미적용)
          conf_threshold: 신뢰도 임계값 (이 값 미만 탐지 제거)
          iou_threshold: IoU 임계값 (NMS용, 현재 미적용)
          device: "CPU" 또는 "CUDA"
        """
        self.model_path = model_path
        self.class_mapping_path = class_mapping_path
        self.image_width, self.image_height = original_size
        self.device = device
        self.score_threshold = score_threshold
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.create_session()

    def create_session(self) -> None:
        """ONNX Runtime 세션을 생성하고 클래스 매핑을 로드한다."""
        opt_session = onnxruntime.SessionOptions()
        # 업스트림은 ORT_DISABLE_ALL을 사용 — 호환성을 위해 유지
        opt_session.graph_optimization_level = (
            onnxruntime.GraphOptimizationLevel.ORT_DISABLE_ALL
        )
        providers = ["CPUExecutionProvider"]
        if self.device.casefold() != "cpu":
            providers.insert(0, "CUDAExecutionProvider")
        session = onnxruntime.InferenceSession(
            self.model_path, opt_session, providers=providers,
        )
        self.session = session
        self.model_inputs = self.session.get_inputs()
        self.input_names = [inp.name for inp in self.model_inputs]
        self.input_shape = self.model_inputs[0].shape
        self.model_output = self.session.get_outputs()
        self.output_names = [out.name for out in self.model_output]
        self.input_height, self.input_width = self.input_shape[2:]

        # 클래스 매핑 로드 (config/ndl.yaml)
        if self.class_mapping_path is not None:
            with open(self.class_mapping_path, "r", encoding="utf-8") as file:
                yaml_file = yaml.safe_load(file)
                self.classes = yaml_file["names"]

    def preprocess(self, img: np.ndarray) -> np.ndarray:
        """이미지를 RTMDet 입력 텐서로 전처리한다.

        처리 흐름:
          1. 정사각형 패딩 (max(H,W)로)
          2. 1280×1280으로 리사이즈
          3. BGR 변환 ([:,:,::-1])
          4. mean/std 정규화 (ImageNet이 아닌 RTMDet 고유 값)
          5. NCHW 전환

        입력: numpy 배열 (H×W×3), RGB
        출력: (1, 3, 1280, 1280) float32 텐서
        """
        # 1. 정사각형 패딩
        max_wh = max(img.shape[0], img.shape[1])
        paddedimg = np.zeros((max_wh, max_wh, 3), dtype=np.uint8)
        paddedimg[: img.shape[0], : img.shape[1], :] = img.copy()
        pil_image = Image.fromarray(paddedimg)
        # 원본 크기 기록 (postprocess에서 좌표 역변환에 사용)
        self.image_width, self.image_height = pil_image.size

        # 2. 리사이즈
        pil_resized = pil_image.resize((self.input_width, self.input_height))
        resized = np.array(pil_resized)

        # 3. BGR 변환
        resized = resized[:, :, ::-1]

        # 4. 정규화 (RTMDet 고유 mean/std — ImageNet과 다름)
        mean = np.array([103.53, 116.28, 123.675], dtype=np.float32)
        std = np.array([57.375, 57.12, 58.395], dtype=np.float32)
        input_image = (resized - mean) / std

        # 5. NCHW 전환
        input_image = input_image.transpose(2, 0, 1)
        input_tensor = input_image[np.newaxis, :, :, :].astype(np.float32)
        return input_tensor

    def postprocess(self, outputs) -> List[dict]:
        """ONNX 출력을 탐지 결과 딕셔너리 목록으로 변환한다.

        ONNX 모델 출력 구조:
          outputs[0] = bboxes — shape (1, N, 5) — [:4] 좌표, [4] 점수
          outputs[1] = class_ids — shape (1, N)

        업스트림 변경사항:
          업스트림은 class_index=1, class_name="line_main"을 하드코딩한다.
          우리 버전은 실제 모델 출력의 class_id를 보존하여 레이아웃 감지에 활용.
        """
        bboxes, class_ids = outputs
        class_ids = np.squeeze(class_ids)
        predictions = np.squeeze(bboxes)

        # 점수(5번째 열)로 필터링
        scores = predictions[:, 4]
        mask = scores > self.conf_threshold
        predictions = predictions[mask, :]
        scores = scores[mask]
        class_ids = class_ids[mask] if class_ids.ndim > 0 else class_ids

        # 좌표 역변환: 모델 좌표 → 원본 이미지 좌표
        boxes = predictions[:, :4].copy()
        boxes /= self.input_width
        boxes *= np.array(
            [self.image_width, self.image_height,
             self.image_width, self.image_height],
        )

        # 2% 세로 패딩 추가 (업스트림과 동일)
        new_boxes = []
        for box in boxes:
            delta_h = (box[3] - box[1]) * 0.02
            new_boxes.append([box[0], box[1] - delta_h, box[2], box[3] + delta_h])

        boxes = np.array(new_boxes).astype(np.int32) if new_boxes else np.empty((0, 4), dtype=np.int32)

        detections = []
        for bbox, score, label in zip(boxes, scores, class_ids):
            # 업스트림은 class_index=1을 하드코딩하지만
            # 우리 버전은 실제 모델 출력의 class_id를 보존한다.
            cls_idx = int(label)
            detections.append({
                "class_index": cls_idx,
                "confidence": float(score),
                "box": bbox.tolist(),
                "class_name": self.classes.get(cls_idx, f"unknown_{cls_idx}"),
            })
        return detections

    def detect(self, img: np.ndarray) -> List[dict]:
        """이미지에서 레이아웃/행을 탐지한다.

        입력: numpy 배열 (H×W×3), RGB
        출력: 탐지 결과 목록
          [{"class_index": int, "confidence": float, "box": [x1,y1,x2,y2], "class_name": str}, ...]
        """
        input_tensor = self.preprocess(img)
        # DEIM과의 차이: ONNX 입력이 1개 (이미지만).
        # DEIM은 {input_names[0]: tensor, input_names[1]: original_size} 2개.
        outputs = self.session.run(
            self.output_names,
            {self.input_names[0]: input_tensor},
        )
        return self.postprocess(outputs)

    def draw_detections(self, npimg: np.ndarray, detections: List[dict]):
        """탐지 결과를 이미지에 그린다 (디버깅용).

        입력:
          npimg: numpy 배열 (H×W×3), RGB
          detections: detect()의 출력

        출력: PIL Image (바운딩 박스가 그려진 이미지)
        """
        pil_image = Image.fromarray(npimg)
        draw = ImageDraw.Draw(pil_image)
        for detection in detections:
            x1, y1, x2, y2 = detection["box"]
            color = (0, 0, 255)  # 파란색
            draw.rectangle([x1, y1, x2, y2], outline=color, width=4)
        return pil_image
