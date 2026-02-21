/**
 * koten-layout-detector — 일본 고전적 레이아웃 감지 라이브러리
 *
 * 원본: https://github.com/yuta1984/koten-layout-detector (MIT License)
 * NDL-DocL 레이아웃 데이터셋으로 학습된 YOLOv12 ONNX 모델.
 *
 * 왜 이렇게 하는가:
 *   원본은 ES 모듈(import/export)이지만, 이 프로젝트는 빌드 도구 없이
 *   일반 <script> 태그로 JS를 로딩한다.
 *   따라서 전역 ort 객체(CDN에서 로드)를 사용하고,
 *   window.KotenLayout으로 API를 노출한다.
 *
 * 의존성: onnxruntime-web (전역 ort 객체)
 */

(function () {
  "use strict";

  // onnxruntime-web이 전역에 로드되어 있는지 확인
  if (typeof ort === "undefined") {
    console.error(
      "koten-layout-detector: onnxruntime-web(ort)이 로드되지 않았습니다. " +
      "index.html에서 ort.min.js CDN을 먼저 로드하세요."
    );
    return;
  }

  /* ─── 상수 ─── */

  /** 모델 입력 크기 (YOLOv12 기본) */
  const MODEL_SIZE = 640;

  /** 레터박스 패딩 색상 (YOLO 기본: 회색 114) */
  const PAD_COLOR = 114;

  /**
   * 클래스 정의 — NDL-DocL 고전적 데이터셋의 5 클래스.
   *
   * id: 모델 출력의 classId
   * key: 영문 식별자
   * ja: 일본어 라벨
   */
  const CLASSES = [
    { id: 0, key: "1_overall",      ja: "全体" },
    { id: 1, key: "2_handwritten",  ja: "手書き" },
    { id: 2, key: "3_typography",   ja: "活字" },
    { id: 3, key: "4_illustration", ja: "図版" },
    { id: 4, key: "5_stamp",        ja: "印判" },
  ];

  /** 클래스별 시각화 색상 */
  const COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6"];

  /* ─── IoU / NMS ─── */

  /**
   * 두 바운딩 박스의 IoU(Intersection over Union)를 계산한다.
   * @param {{ x1: number, y1: number, x2: number, y2: number }} a
   * @param {{ x1: number, y1: number, x2: number, y2: number }} b
   * @returns {number} IoU 값 (0~1)
   */
  function iou(a, b) {
    const ix1 = Math.max(a.x1, b.x1);
    const iy1 = Math.max(a.y1, b.y1);
    const ix2 = Math.min(a.x2, b.x2);
    const iy2 = Math.min(a.y2, b.y2);

    const interW = Math.max(0, ix2 - ix1);
    const interH = Math.max(0, iy2 - iy1);
    const interArea = interW * interH;

    const areaA = (a.x2 - a.x1) * (a.y2 - a.y1);
    const areaB = (b.x2 - b.x1) * (b.y2 - b.y1);
    const unionArea = areaA + areaB - interArea;

    return unionArea <= 0 ? 0 : interArea / unionArea;
  }

  /**
   * Non-Maximum Suppression을 적용한다.
   * 클래스별로 confidence 높은 순서대로 겹치는 박스를 제거한다.
   *
   * @param {Array} detections - { x1, y1, x2, y2, conf, classId } 배열
   * @param {number} iouThreshold - IoU 임계값 (기본 0.45)
   * @returns {Array} NMS 적용 후 검출 결과
   */
  function nms(detections, iouThreshold) {
    if (iouThreshold === undefined) iouThreshold = 0.45;

    var classIds = [];
    var seen = {};
    for (var i = 0; i < detections.length; i++) {
      var cid = detections[i].classId;
      if (!seen[cid]) {
        seen[cid] = true;
        classIds.push(cid);
      }
    }

    var result = [];

    for (var ci = 0; ci < classIds.length; ci++) {
      var boxes = detections
        .filter(function (d) { return d.classId === classIds[ci]; })
        .sort(function (a, b) { return b.conf - a.conf; });

      while (boxes.length > 0) {
        var best = boxes.shift();
        result.push(best);
        boxes = boxes.filter(function (b) { return iou(best, b) < iouThreshold; });
      }
    }

    return result;
  }

  /* ─── 모델 로드 ─── */

  /**
   * ONNX 세션을 생성하여 반환한다.
   *
   * 왜 이렇게 하는가:
   *   모델은 한 번만 로드하고 캐시하여 재사용한다.
   *   WASM 실행 프로바이더를 사용하여 CPU에서 추론한다.
   *
   * @param {string} modelUrl - ONNX 모델 파일 URL
   * @returns {Promise<ort.InferenceSession>}
   */
  async function loadModel(modelUrl) {
    // WASM 파일 경로를 CDN으로 설정
    ort.env.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.21.0/dist/";

    var session = await ort.InferenceSession.create(modelUrl, {
      executionProviders: ["wasm"],
      graphOptimizationLevel: "all",
    });
    return session;
  }

  /* ─── 전처리 ─── */

  /**
   * 이미지를 레터박스 리사이즈하여 Float32 텐서로 변환한다.
   *
   * 왜 레터박스인가:
   *   YOLO 모델은 정사각형(640×640) 입력을 요구한다.
   *   원본 비율을 유지하면서 패딩으로 정사각형을 만든다.
   *   meta에 scale/padX/padY를 기록하여, 후처리에서 원본 좌표로 역변환한다.
   *
   * @param {HTMLImageElement | HTMLCanvasElement} img - 입력 이미지
   * @returns {{ tensor: ort.Tensor, meta: { scale, padX, padY, origW, origH } }}
   */
  function preprocess(img) {
    var canvas = document.createElement("canvas");
    canvas.width = MODEL_SIZE;
    canvas.height = MODEL_SIZE;
    var ctx = canvas.getContext("2d");

    // 패딩 색상으로 채우기
    ctx.fillStyle = "rgb(" + PAD_COLOR + "," + PAD_COLOR + "," + PAD_COLOR + ")";
    ctx.fillRect(0, 0, MODEL_SIZE, MODEL_SIZE);

    // 비율 유지 축소
    var imgWidth = img.naturalWidth || img.width;
    var imgHeight = img.naturalHeight || img.height;
    var scale = Math.min(MODEL_SIZE / imgWidth, MODEL_SIZE / imgHeight);
    var newW = Math.round(imgWidth * scale);
    var newH = Math.round(imgHeight * scale);
    var padX = Math.floor((MODEL_SIZE - newW) / 2);
    var padY = Math.floor((MODEL_SIZE - newH) / 2);

    ctx.drawImage(img, padX, padY, newW, newH);

    var imageData = ctx.getImageData(0, 0, MODEL_SIZE, MODEL_SIZE);
    var data = imageData.data;

    // HWC (RGBA) → CHW (RGB) Float32, 정규화 ÷255
    var float32 = new Float32Array(3 * MODEL_SIZE * MODEL_SIZE);
    var pixelCount = MODEL_SIZE * MODEL_SIZE;
    for (var i = 0; i < pixelCount; i++) {
      float32[i]                  = data[i * 4]     / 255.0; // R
      float32[i + pixelCount]     = data[i * 4 + 1] / 255.0; // G
      float32[i + pixelCount * 2] = data[i * 4 + 2] / 255.0; // B
    }

    return {
      tensor: new ort.Tensor("float32", float32, [1, 3, MODEL_SIZE, MODEL_SIZE]),
      meta: { scale: scale, padX: padX, padY: padY, origW: imgWidth, origH: imgHeight },
    };
  }

  /* ─── 추론 ─── */

  /**
   * ONNX 세션으로 추론을 실행한다.
   *
   * @param {ort.InferenceSession} session
   * @param {ort.Tensor} tensor
   * @returns {Promise<ort.Tensor>} 출력 텐서 [1, 9, 8400]
   */
  async function runInference(session, tensor) {
    var inputName = session.inputNames[0];
    var feeds = {};
    feeds[inputName] = tensor;
    var results = await session.run(feeds);
    return results[session.outputNames[0]];
  }

  /* ─── 후처리 ─── */

  /**
   * ONNX 출력 텐서를 검출 결과 배열로 변환한다.
   *
   * 왜 이렇게 하는가:
   *   모델 출력은 [1, 4+nc, 8400] 형태이다.
   *   각 예측마다 cx/cy/w/h + 클래스별 점수가 들어있다.
   *   confidence 임계값으로 필터링 후, NMS로 중복을 제거한다.
   *   레터박스 패딩/스케일을 역변환하여 원본 이미지 좌표로 돌린다.
   *
   * @param {ort.Tensor} outputTensor - 모델 출력 [1, 4+nc, 8400]
   * @param {Object} meta - preprocess()가 반환한 meta
   * @param {number} [confThreshold=0.5] - confidence 임계값
   * @param {number} [iouThreshold=0.45] - NMS IoU 임계값
   * @returns {Array<{ x1, y1, x2, y2, conf, classId, label, color }>}
   */
  function postprocess(outputTensor, meta, confThreshold, iouThreshold) {
    if (confThreshold === undefined) confThreshold = 0.5;
    if (iouThreshold === undefined) iouThreshold = 0.45;

    var dims = outputTensor.dims;
    var numChannels = dims[1];
    var numPreds = dims[2];
    var data = outputTensor.data;
    var nc = numChannels - 4; // 클래스 수

    var raw = [];

    for (var i = 0; i < numPreds; i++) {
      // 클래스별 점수 최대값과 ID
      var maxScore = -Infinity;
      var classId = 0;
      for (var c = 0; c < nc; c++) {
        var score = data[(4 + c) * numPreds + i];
        if (score > maxScore) {
          maxScore = score;
          classId = c;
        }
      }

      if (maxScore < confThreshold) continue;

      // cx, cy, w, h (640px 스케일) → x1, y1, x2, y2 (원본 이미지 스케일)
      var cx = data[0 * numPreds + i];
      var cy = data[1 * numPreds + i];
      var w  = data[2 * numPreds + i];
      var h  = data[3 * numPreds + i];

      // 레터박스 패딩/축소를 원복
      var x1 = ((cx - w / 2) - meta.padX) / meta.scale;
      var y1 = ((cy - h / 2) - meta.padY) / meta.scale;
      var x2 = ((cx + w / 2) - meta.padX) / meta.scale;
      var y2 = ((cy + h / 2) - meta.padY) / meta.scale;

      raw.push({ x1: x1, y1: y1, x2: x2, y2: y2, conf: maxScore, classId: classId });
    }

    var kept = nms(raw, iouThreshold);

    return kept.map(function (d) {
      return {
        x1: d.x1,
        y1: d.y1,
        x2: d.x2,
        y2: d.y2,
        conf: d.conf,
        classId: d.classId,
        label: CLASSES[d.classId] ? CLASSES[d.classId].ja : String(d.classId),
        color: COLORS[d.classId] || "#ffffff",
      };
    });
  }

  /* ─── 전역 노출 ─── */

  window.KotenLayout = {
    loadModel: loadModel,
    preprocess: preprocess,
    runInference: runInference,
    postprocess: postprocess,
    CLASSES: CLASSES,
    COLORS: COLORS,
    iou: iou,
    nms: nms,
  };

})();
