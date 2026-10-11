# 함께 싣는 화면 라이브러리

인터넷이 없어도 PDF 보기·그래프가 되도록 CDN 대신 여기에 둔다
(2026-10-11 전수 — 전에는 CDN이라 오프라인 첫 실행에서 PDF가 뜨지 않았다).
브라우저 레이아웃 탐지는 실행기(onnxruntime-web)만 여기 있고 **모델(.onnx, 약 36MB)은 저장소에 싣지 않는다** —
처음 쓸 때 `static/models/`에 없으면 GitHub에서 받는다(`js/layout-editor.js`). 그 한 번은 인터넷이 필요하다.
받을 때 jsDelivr 목록의 sha256과 맞춰 보았다. 판을 올리면 이 표와 `index.html`·
`js/pdf-renderer.js`·`js/koten-layout-detector.js`의 경로를 함께 고친다.

| 폴더 | 판 | 출처 | 라이선스 |
|---|---|---|---|
| `pdfjs/` | pdfjs-dist 3.11.174 (`build/pdf.min.js`·`pdf.worker.min.js`) | npm | Apache-2.0 (`LICENSE`) |
| `d3/` | d3 7.9.0 (`dist/d3.min.js`) | npm | ISC (`LICENSE`) |
| `onnxruntime-web/` | onnxruntime-web 1.21.0 (`dist/ort.min.js`·`ort-wasm-simd-threaded.{mjs,wasm}`) | npm, LICENSE는 microsoft/onnxruntime v1.21.0 | MIT (`LICENSE`) |
