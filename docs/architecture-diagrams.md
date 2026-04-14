# 아키텍처 다이어그램

> 2026-03-14 기준. HTML/CSS 아키텍처 다이어그램으로 작성.
> 마크다운 뷰어에서 직접 렌더링 가능.
>
> **구성**: 12개 다이어그램 — 데이터 모델(1-3), 시스템 아키텍처(4-5), 워크플로우(6-7), 스키마(8-9), 저장소(10-11), UI(12)

---

## 1. 8층 데이터 모델

원본 저장소(L1-L4, 단일 정본)와 해석 저장소(L5-L8, 다수 병존)의 구조.
저장소 경계에서 `dependency.json`이 변경을 추적한다.

<div style="max-width: 1200px; width: 100%; margin: 0 auto;">
<style scoped>
.arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #78350f; margin-bottom: 16px; }
.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 2px 6px rgba(120, 53, 15, 0.08); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
.arch-box { border-radius: 5px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #44220e; background: #fffcf7; border: 1px solid #d4c4a8; }.arch-box.highlight { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #b45309; }.arch-box.tech { font-size: 10px; color: #78350f; background: #f5efe6; }
.arch-layer.external { background: linear-gradient(135deg, #f5efe5 0%, #ede4d4 100%); border: 2px dashed #b8a080; }.arch-layer.external .arch-layer-title { color: #8a7a68; }.arch-layer.user { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #d97706; }.arch-layer.user .arch-layer-title { color: #92400e; }.arch-layer.application { background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c; }.arch-layer.application .arch-layer-title { color: #9a3412; }.arch-layer.ai { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626; }.arch-layer.ai .arch-layer-title { color: #991b1b; }.arch-layer.data { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 2px solid #059669; }.arch-layer.data .arch-layer-title { color: #065f46; }.arch-layer.infra { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); border: 2px solid #64748b; }.arch-layer.infra .arch-layer-title { color: #334155; }
.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f0ead8 0%, #e5dcca 100%); border: 2px solid #c4b498; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(120, 53, 15, 0.06); }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #78350f; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #44220e; background: #fffcf7; padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid #d4c4a8; }.arch-sidebar-item.metric { background: #fef3c7; border: 1px solid #d97706; color: #92400e; font-weight: 600; }
</style>
<div class="arch-title">8층 데이터 모델</div>
<div class="arch-wrapper">
<div class="arch-main">
<div class="arch-layer data">
<div class="arch-layer-title">원본 저장소 (L1-L4) — 단일 정본, 정답이 있는 층</div>
<div class="arch-grid arch-grid-4">
<div class="arch-box highlight"><b>L1 이미지/PDF</b><br/>불변 원본 · 수정 금지<br/><i>manifest · bibliography</i></div>
<div class="arch-box"><b>L2 OCR 글자해독</b><br/>글자 + 좌표 + 신뢰도<br/><i>ocr_page</i></div>
<div class="arch-box"><b>L3 레이아웃 분석</b><br/>본문/주석/서문 구분 · 읽기 순서<br/><i>layout_page (LayoutBlock)</i></div>
<div class="arch-box"><b>L4 사람 수정</b><br/>OCR 교정 · 이체자 확인 · 확정본<br/><i>corrections</i></div>
</div>
<div style="text-align: center; font-size: 10px; color: #065f46; margin-top: 6px;">L1 → L2 → L3 → L4</div>
</div>
<div class="arch-layer application">
<div class="arch-layer-title">저장소 경계</div>
<div class="arch-box highlight" style="max-width: 320px; margin: 0 auto;">dependency.json<br/>파일 해시 · 커밋 추적 · 변경 경고</div>
</div>
<div class="arch-layer" style="background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%); border: 2px solid #4f46e5;">
<div class="arch-layer-title" style="color: #3730a3;">해석 저장소 (L5-L8) — 다수 해석 병존, 정답 없음</div>
<div class="arch-grid arch-grid-4">
<div class="arch-box"><b>L5 표점 · 현토</b><br/>句讀 삽입 · 懸吐 달기<br/><i>punctuation_page · hyeonto_page</i></div>
<div class="arch-box"><b>L6 번역</b><br/>현대어역 · 다국어<br/><i>translation_page</i></div>
<div class="arch-box"><b>L7 주석 · 사전</b><br/>인물/지명 태깅 · 사전형 주석 · 인용마크<br/><i>annotation_page v2 · citation_mark_page</i></div>
<div class="arch-box"><b>L8 외부연계</b><br/>DB · API · 학술 네트워크<br/><i>relation (코어)</i></div>
</div>
<div style="text-align: center; font-size: 10px; color: #3730a3; margin-top: 6px;">L5 → L6 → L7 → L8</div>
</div>
</div>
<div class="arch-sidebar">
<div class="arch-sidebar-panel">
<div class="arch-sidebar-title">코어 스키마 엔티티</div>
<div class="arch-sidebar-item metric">Work</div>
<div class="arch-sidebar-item metric">TextBlock</div>
<div class="arch-sidebar-item metric">Tag</div>
<div class="arch-sidebar-item">↓ 승격 (선택적)</div>
<div class="arch-sidebar-item metric">Concept</div>
<div class="arch-sidebar-item metric">Agent</div>
<div class="arch-sidebar-item metric">Relation</div>
</div>
<div class="arch-sidebar-panel">
<div class="arch-sidebar-title">저장소 경계</div>
<div class="arch-sidebar-item">dependency.json</div>
<div class="arch-sidebar-item tech" style="font-size: 9px;">파일 해시 비교<br/>변경 경고 전파</div>
</div>
</div>
</div>
</div>

**핵심 원칙:**
- 원본 저장소는 **단일 정본**으로 수렴 (정답이 있다)
- 해석 저장소는 **다수 병존** (해석은 연구자마다 다르다)
- L4 확정 → `dependency.json` → 해석 저장소 시작점 (저장소 경계)
- 코어 스키마 6개 엔티티(Work, TextBlock, Tag, Concept, Agent, Relation)는 해석 저장소 내부에 위치

---

## 2. 전체 시스템 아키텍처

프론트엔드(27개 JS 모듈) · 백엔드(FastAPI + 8 라우터) · 처리 엔진(OCR 5종 + LLM 4단) · Git 저장소 · 외부 서비스.

<div style="max-width: 1200px; width: 100%; margin: 0 auto;">
<style scoped>
.arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #78350f; margin-bottom: 16px; }
.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 2px 6px rgba(120, 53, 15, 0.08); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
.arch-box { border-radius: 5px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #44220e; background: #fffcf7; border: 1px solid #d4c4a8; }.arch-box.highlight { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #b45309; }.arch-box.tech { font-size: 10px; color: #78350f; background: #f5efe6; }
.arch-layer.external { background: linear-gradient(135deg, #f5efe5 0%, #ede4d4 100%); border: 2px dashed #b8a080; }.arch-layer.external .arch-layer-title { color: #8a7a68; }.arch-layer.user { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #d97706; }.arch-layer.user .arch-layer-title { color: #92400e; }.arch-layer.application { background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c; }.arch-layer.application .arch-layer-title { color: #9a3412; }.arch-layer.ai { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626; }.arch-layer.ai .arch-layer-title { color: #991b1b; }.arch-layer.data { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 2px solid #059669; }.arch-layer.data .arch-layer-title { color: #065f46; }.arch-layer.infra { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); border: 2px solid #64748b; }.arch-layer.infra .arch-layer-title { color: #334155; }
.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f0ead8 0%, #e5dcca 100%); border: 2px solid #c4b498; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(120, 53, 15, 0.06); }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #78350f; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #44220e; background: #fffcf7; padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid #d4c4a8; }.arch-sidebar-item.metric { background: #fef3c7; border: 1px solid #d97706; color: #92400e; font-weight: 600; }
</style>
<div class="arch-title">전체 시스템 아키텍처</div>
<div class="arch-wrapper">
<div class="arch-sidebar">
<div class="arch-sidebar-panel">
<div class="arch-sidebar-title">Git 저장소 (로컬)</div>
<div class="arch-sidebar-item metric">원본 저장소<br/>L1-L4</div>
<div class="arch-sidebar-item metric">해석 저장소<br/>L5-L8 (다수)</div>
<div class="arch-sidebar-item">library_manifest.json<br/>서고 전체 지도</div>
</div>
</div>
<div class="arch-main">
<div class="arch-layer user">
<div class="arch-layer-title">프론트엔드 (Vanilla JS · 빌드 도구 없음)</div>
<div style="font-size: 10px; font-weight: 600; color: #92400e; margin-bottom: 4px;">코어 UI</div>
<div class="arch-grid arch-grid-3" style="margin-bottom: 8px;">
<div class="arch-box highlight">workspace.js<br/>메인 오케스트레이션</div>
<div class="arch-box">pdf-renderer.js<br/>PDF.js 뷰어</div>
<div class="arch-box">sidebar-tree.js<br/>문헌/권/페이지 탐색</div>
</div>
<div style="font-size: 10px; font-weight: 600; color: #92400e; margin-bottom: 4px;">원본 작업 (L1-L4)</div>
<div class="arch-grid arch-grid-3" style="margin-bottom: 8px;">
<div class="arch-box">layout-editor.js<br/>L3 영역 편집</div>
<div class="arch-box">correction-editor.js<br/>L4 텍스트 교정</div>
<div class="arch-box">batch-correction.js<br/>일괄 이체자 교정</div>
</div>
<div style="font-size: 10px; font-weight: 600; color: #92400e; margin-bottom: 4px;">해석 작업 (L5-L8)</div>
<div class="arch-grid arch-grid-5" style="margin-bottom: 8px;">
<div class="arch-box">punctuation-editor.js<br/>L5 표점</div>
<div class="arch-box">hyeonto-editor.js<br/>L5 현토</div>
<div class="arch-box">translation-editor.js<br/>L6 번역</div>
<div class="arch-box">annotation-editor.js<br/>L7 주석</div>
<div class="arch-box">citation-editor.js<br/>L7 인용마크</div>
</div>
<div style="font-size: 10px; font-weight: 600; color: #92400e; margin-bottom: 4px;">지원 모듈</div>
<div class="arch-grid arch-grid-4">
<div class="arch-box tech">interpretation.js<br/>해석 관리</div>
<div class="arch-box tech">entity-manager.js<br/>코어 엔티티</div>
<div class="arch-box tech">git-graph.js<br/>Git 이력</div>
<div class="arch-box tech">ocr-panel.js<br/>OCR 선택</div>
<div class="arch-box tech">bibliography.js<br/>서지정보</div>
<div class="arch-box tech">notes-panel.js<br/>페이지 비고</div>
<div class="arch-box tech">hwp-import.js<br/>HWP 가져오기</div>
<div class="arch-box tech">alignment-view.js<br/>이체자 정렬</div>
</div>
</div>
<div style="text-align: center; font-size: 11px; color: #78350f; margin: 4px 0;">↕ REST API</div>
<div class="arch-layer application">
<div class="arch-layer-title">백엔드 (Python · FastAPI)</div>
<div class="arch-grid arch-grid-2" style="margin-bottom: 8px;">
<div class="arch-box highlight">server.py<br/>앱 생성 + 라우터 마운트 (~85줄)</div>
<div class="arch-box highlight">_state.py<br/>공유 상태 · 헬퍼 · LLM/OCR 캐시</div>
</div>
<div style="font-size: 10px; font-weight: 600; color: #9a3412; margin-bottom: 4px;">8개 도메인 라우터 (158 API)</div>
<div class="arch-grid arch-grid-4">
<div class="arch-box">library<br/><b>15</b></div>
<div class="arch-box">documents<br/><b>32</b></div>
<div class="arch-box">interpretations<br/><b>22</b></div>
<div class="arch-box">llm_ocr<br/><b>13</b></div>
<div class="arch-box">alignment<br/><b>17</b></div>
<div class="arch-box">reading<br/><b>24</b></div>
<div class="arch-box">annotation<br/><b>32</b></div>
<div class="arch-box">version<br/><b>7</b></div>
</div>
</div>
<div style="text-align: center; font-size: 11px; color: #78350f; margin: 4px 0;">↓</div>
<div class="arch-layer ai">
<div class="arch-layer-title">처리 엔진</div>
<div class="arch-grid arch-grid-3">
<div style="padding: 6px;">
<div style="font-size: 10px; font-weight: 600; color: #991b1b; margin-bottom: 4px; text-align: center;">OCR 엔진 (registry.py)</div>
<div class="arch-box" style="margin: 3px 0;">NDL古典籍OCR Full (TrOCR)</div>
<div class="arch-box" style="margin: 3px 0;">NDL古典籍OCR-Lite (ONNX)</div>
<div class="arch-box" style="margin: 3px 0;">NDLOCR-Lite</div>
<div class="arch-box" style="margin: 3px 0;">LLM Vision OCR</div>
<div class="arch-box" style="margin: 3px 0;">PaddleOCR</div>
</div>
<div style="padding: 6px;">
<div style="font-size: 10px; font-weight: 600; color: #991b1b; margin-bottom: 4px; text-align: center;">LLM 라우터 (router.py)</div>
<div class="arch-box" style="margin: 3px 0;">1. Base44 HTTP</div>
<div class="arch-box" style="margin: 3px 0;">2. Base44 Bridge</div>
<div class="arch-box" style="margin: 3px 0;">3. Ollama 프록시</div>
<div class="arch-box" style="margin: 3px 0;">4. 직접 API</div>
</div>
<div style="padding: 6px;">
<div style="font-size: 10px; font-weight: 600; color: #991b1b; margin-bottom: 4px; text-align: center;">기타</div>
<div class="arch-box" style="margin: 3px 0;">jsonschema 검증</div>
<div class="arch-box" style="margin: 3px 0;">HWP/HWPX 파서</div>
<div class="arch-box" style="margin: 3px 0;">서지 파서<br/>(NDL · KORCIS · Archives.JP)</div>
</div>
</div>
</div>
</div>
<div class="arch-sidebar">
<div class="arch-sidebar-panel">
<div class="arch-sidebar-title">외부 서비스</div>
<div class="arch-sidebar-item metric">Gemini · OpenAI<br/>Anthropic</div>
<div class="arch-sidebar-item">Ollama Server</div>
<div class="arch-sidebar-item">GitHub · GitLab<br/>(백업/동기화)</div>
<div class="arch-sidebar-item">NDL · KORCIS<br/>(서지 API)</div>
</div>
</div>
</div>
</div>

**역할 분리:**
- **Git**: 저장, 이력, 버전, diff → 이미 있는 인프라
- **앱**: 관계, 의미, 경고, UI → 만들어야 할 것
- **원격 호스팅**: 백업, 동기화 → 교체 가능
- **오프라인 퍼스트**: 핵심 작업(교정, 열람, 커밋)은 인터넷 없이 완전히 동작

---

## 3. 코어 스키마 엔티티 관계 (ER Diagram)

해석 저장소 내부의 6개 엔티티 모델. core-schema-v1.3 기준.
모든 엔티티는 `draft → active → deprecated → archived` 상태 전이를 따른다 (삭제 금지).

<div style="max-width: 1200px; width: 100%; margin: 0 auto;">
<style scoped>
.arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #78350f; margin-bottom: 16px; }
.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 2px 6px rgba(120, 53, 15, 0.08); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
.arch-box { border-radius: 5px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #44220e; background: #fffcf7; border: 1px solid #d4c4a8; }.arch-box.highlight { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #b45309; }.arch-box.tech { font-size: 10px; color: #78350f; background: #f5efe6; }
.arch-layer.external { background: linear-gradient(135deg, #f5efe5 0%, #ede4d4 100%); border: 2px dashed #b8a080; }.arch-layer.external .arch-layer-title { color: #8a7a68; }.arch-layer.user { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #d97706; }.arch-layer.user .arch-layer-title { color: #92400e; }.arch-layer.application { background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c; }.arch-layer.application .arch-layer-title { color: #9a3412; }.arch-layer.ai { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626; }.arch-layer.ai .arch-layer-title { color: #991b1b; }.arch-layer.data { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 2px solid #059669; }.arch-layer.data .arch-layer-title { color: #065f46; }.arch-layer.infra { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); border: 2px solid #64748b; }.arch-layer.infra .arch-layer-title { color: #334155; }
.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f0ead8 0%, #e5dcca 100%); border: 2px solid #c4b498; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(120, 53, 15, 0.06); }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #78350f; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #44220e; background: #fffcf7; padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid #d4c4a8; }.arch-sidebar-item.metric { background: #fef3c7; border: 1px solid #d97706; color: #92400e; font-weight: 600; }
</style>
<div class="arch-title">코어 스키마 엔티티 관계</div>
<div class="arch-layer" style="background: linear-gradient(135deg, #fdf6e3 0%, #f5efe6 100%); border: 2px solid #c4b498;">
<div class="arch-layer-title" style="color: #78350f;">6개 엔티티 — 해석 저장소 내부</div>
<div class="arch-grid arch-grid-3">
<div class="arch-box highlight" style="text-align: left; padding: 10px;">
<div style="font-size: 12px; font-weight: bold; text-align: center; margin-bottom: 6px;">Work</div>
<div style="font-size: 10px; line-height: 1.5;">
id: UUID (PK)<br/>
title: 원어 제목 (필수)<br/>
author: 저자<br/>
period: 시대<br/>
status: draft|active|deprecated|archived<br/>
metadata: 자유 확장 필드
</div>
</div>
<div class="arch-box highlight" style="text-align: left; padding: 10px;">
<div style="font-size: 12px; font-weight: bold; text-align: center; margin-bottom: 6px;">TextBlock</div>
<div style="font-size: 10px; line-height: 1.5;">
id: UUID (PK)<br/>
work_id: FK → Work<br/>
sequence_index: 순서 (필수)<br/>
original_text: 원문 (불변, 필수)<br/>
normalized_text: 정규화<br/>
source_ref: 출처 추적 JSON<br/>
status: draft|active|…
</div>
</div>
<div class="arch-box" style="text-align: left; padding: 10px;">
<div style="font-size: 12px; font-weight: bold; text-align: center; margin-bottom: 6px;">Tag</div>
<div style="font-size: 10px; line-height: 1.5;">
id: UUID (PK)<br/>
block_id: FK → TextBlock<br/>
surface: 표면 텍스트 (필수)<br/>
core_category: person|place|…<br/>
confidence: 신뢰도 0-1<br/>
extractor: llm|rule|human<br/>
status: draft|active|…
</div>
</div>
<div class="arch-box" style="text-align: left; padding: 10px;">
<div style="font-size: 12px; font-weight: bold; text-align: center; margin-bottom: 6px;">Concept</div>
<div style="font-size: 10px; line-height: 1.5;">
id: UUID (PK)<br/>
label: 대표 이름 (필수)<br/>
scope_work: 범위 Work (선택)<br/>
description: 학술 설명<br/>
concept_features: 자유 확장<br/>
status: draft|active|…
</div>
</div>
<div class="arch-box" style="text-align: left; padding: 10px;">
<div style="font-size: 12px; font-weight: bold; text-align: center; margin-bottom: 6px;">Agent</div>
<div style="font-size: 10px; line-height: 1.5;">
id: UUID (PK)<br/>
name: 이름 (필수)<br/>
period: 활동 시대<br/>
biography_note: 약전<br/>
status: draft|active|…
</div>
</div>
<div class="arch-box" style="text-align: left; padding: 10px;">
<div style="font-size: 12px; font-weight: bold; text-align: center; margin-bottom: 6px;">Relation</div>
<div style="font-size: 10px; line-height: 1.5;">
id: UUID (PK)<br/>
subject_id / subject_type<br/>
predicate: snake_case (필수)<br/>
object_id / object_type<br/>
object_value: 자유 텍스트<br/>
evidence_blocks: TextBlock ID[]<br/>
confidence / status
</div>
</div>
</div>
<div style="text-align: center; font-size: 10px; color: #78350f; margin-top: 10px; line-height: 1.6;">
Work ←contains— TextBlock ←has tags— Tag —승격→ Concept<br/>
Agent / Concept —subject|object— Relation ←evidence— TextBlock
</div>
</div>
</div>

**설계 보장:**
- 구조(Structure) ≠ 해석(Interpretation) — 코어는 구조만 저장
- 온톨로지 잠금 없음 — Concept의 `concept_features`는 자유 확장
- Tag → Concept 승격은 연구자 판단 (선택적, Promotion Flow)
- Predicate는 snake_case, 구조적 행위만 (해석 배제)
- `source_ref`로 원본 저장소 역참조 (document_id + page + layout_block_id + git commit)

---

## 4. LLM 4단 폴백 아키텍처

전체 프로젝트 공용 LLM 연동. `src/llm/router.py`가 단일 진입점.
자동으로 1순위부터 시도, 실패 시 다음으로 폴백.

<div style="max-width: 1200px; width: 100%; margin: 0 auto;">
<style scoped>
.arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #78350f; margin-bottom: 16px; }
.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 2px 6px rgba(120, 53, 15, 0.08); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
.arch-box { border-radius: 5px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #44220e; background: #fffcf7; border: 1px solid #d4c4a8; }.arch-box.highlight { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #b45309; }.arch-box.tech { font-size: 10px; color: #78350f; background: #f5efe6; }
.arch-layer.external { background: linear-gradient(135deg, #f5efe5 0%, #ede4d4 100%); border: 2px dashed #b8a080; }.arch-layer.external .arch-layer-title { color: #8a7a68; }.arch-layer.user { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #d97706; }.arch-layer.user .arch-layer-title { color: #92400e; }.arch-layer.application { background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c; }.arch-layer.application .arch-layer-title { color: #9a3412; }.arch-layer.ai { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626; }.arch-layer.ai .arch-layer-title { color: #991b1b; }.arch-layer.data { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 2px solid #059669; }.arch-layer.data .arch-layer-title { color: #065f46; }.arch-layer.infra { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); border: 2px solid #64748b; }.arch-layer.infra .arch-layer-title { color: #334155; }
.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f0ead8 0%, #e5dcca 100%); border: 2px solid #c4b498; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(120, 53, 15, 0.06); }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #78350f; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #44220e; background: #fffcf7; padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid #d4c4a8; }.arch-sidebar-item.metric { background: #fef3c7; border: 1px solid #d97706; color: #92400e; font-weight: 600; }
</style>
<div class="arch-title">LLM 4단 폴백 아키텍처</div>
<div class="arch-wrapper">
<div class="arch-main">
<div class="arch-layer application">
<div class="arch-layer-title">LLM 호출 진입점</div>
<div class="arch-box highlight" style="max-width: 400px; margin: 0 auto;">src/llm/router.py<br/><b>LLMRouter</b> — 단일 진입점 · 자동 폴백</div>
</div>
<div style="text-align: center; font-size: 11px; color: #78350f;">↓ 시도</div>
<div class="arch-layer data">
<div class="arch-layer-title">1순위: Base44 InvokeLLM (HTTP)</div>
<div class="arch-box" style="max-width: 400px; margin: 0 auto;">localhost:8787/api/chat<br/>agent-chat 서버 경유 · 무료 · 이미지 분석 · MCP 도구</div>
</div>
<div style="text-align: center; font-size: 11px; color: #78350f;">↓ 실패 시</div>
<div class="arch-layer" style="background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c;">
<div class="arch-layer-title" style="color: #9a3412;">2순위: Base44 Bridge (Node.js)</div>
<div class="arch-box" style="max-width: 400px; margin: 0 auto;">subprocess: node invoke.js<br/>backend-44 SDK 직접 호출 · 서버 없이 1회성 호출</div>
</div>
<div style="text-align: center; font-size: 11px; color: #78350f;">↓ 실패 시</div>
<div class="arch-layer" style="background: linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%); border: 2px solid #7c3aed;">
<div class="arch-layer-title" style="color: #5b21b6;">3순위: Ollama (로컬 프록시)</div>
<div class="arch-box" style="max-width: 400px; margin: 0 auto; margin-bottom: 8px;">localhost:11434 — 클라우드 모델 로컬 프록시</div>
<div class="arch-grid arch-grid-4">
<div class="arch-box tech">Qwen3-VL</div>
<div class="arch-box tech">Kimi-K2.5</div>
<div class="arch-box tech">GLM-5</div>
<div class="arch-box tech">Gemini-3-Flash</div>
</div>
</div>
<div style="text-align: center; font-size: 11px; color: #78350f;">↓ 실패 시</div>
<div class="arch-layer ai">
<div class="arch-layer-title">4순위: 직접 API 호출</div>
<div class="arch-grid arch-grid-3">
<div class="arch-box">Anthropic<br/>Claude</div>
<div class="arch-box">OpenAI<br/>GPT</div>
<div class="arch-box">Google<br/>Gemini</div>
</div>
</div>
<div class="arch-layer infra">
<div class="arch-layer-title">LLM 소비자 (src/core/)</div>
<div class="arch-grid arch-grid-6">
<div class="arch-box">punctuation_llm.py<br/>L5 표점 초안</div>
<div class="arch-box">hyeonto.py<br/>L5 현토 초안</div>
<div class="arch-box">translation_llm.py<br/>L6 번역 초안</div>
<div class="arch-box">annotation_llm.py<br/>L7 주석 자동생성</div>
<div class="arch-box">annotation_dict_llm.py<br/>L7 사전 생성</div>
<div class="arch-box">draft.py<br/>범용 LLM 초안</div>
</div>
</div>
</div>
<div class="arch-sidebar">
<div class="arch-sidebar-panel">
<div class="arch-sidebar-title">설정 (config.py)</div>
<div class="arch-sidebar-item metric">환경변수</div>
<div class="arch-sidebar-item">↓</div>
<div class="arch-sidebar-item metric">.env 파일<br/>(프로젝트 · 서고)</div>
<div class="arch-sidebar-item">↓</div>
<div class="arch-sidebar-item metric">기본값</div>
</div>
<div class="arch-sidebar-panel">
<div class="arch-sidebar-title">사용량 추적</div>
<div class="arch-sidebar-item">usage_tracker.py<br/>토큰 · 비용 · 모델별 집계</div>
</div>
</div>
</div>
</div>

**LLM 협업 패턴 (2-8층 공통):**
1. LLM이 draft 생성
2. 사람이 review
3. 사람이 commit (Git 자동 저장)

---

## 5. OCR 엔진 파이프라인

5개 OCR 엔진의 레지스트리 기반 자동 선택. LayoutBlock 단위로 이미지 크롭 → 전처리 → 인식 → 후처리.

<div style="max-width: 1200px; width: 100%; margin: 0 auto;">
<style scoped>
.arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #78350f; margin-bottom: 16px; }
.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 2px 6px rgba(120, 53, 15, 0.08); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
.arch-box { border-radius: 5px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #44220e; background: #fffcf7; border: 1px solid #d4c4a8; }.arch-box.highlight { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #b45309; }.arch-box.tech { font-size: 10px; color: #78350f; background: #f5efe6; }
.arch-layer.external { background: linear-gradient(135deg, #f5efe5 0%, #ede4d4 100%); border: 2px dashed #b8a080; }.arch-layer.external .arch-layer-title { color: #8a7a68; }.arch-layer.user { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #d97706; }.arch-layer.user .arch-layer-title { color: #92400e; }.arch-layer.application { background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c; }.arch-layer.application .arch-layer-title { color: #9a3412; }.arch-layer.ai { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626; }.arch-layer.ai .arch-layer-title { color: #991b1b; }.arch-layer.data { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 2px solid #059669; }.arch-layer.data .arch-layer-title { color: #065f46; }.arch-layer.infra { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); border: 2px solid #64748b; }.arch-layer.infra .arch-layer-title { color: #334155; }
.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f0ead8 0%, #e5dcca 100%); border: 2px solid #c4b498; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(120, 53, 15, 0.06); }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #78350f; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #44220e; background: #fffcf7; padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid #d4c4a8; }.arch-sidebar-item.metric { background: #fef3c7; border: 1px solid #d97706; color: #92400e; font-weight: 600; }
</style>
<div class="arch-title">OCR 엔진 파이프라인</div>
<div style="display: flex; gap: 10px; align-items: stretch; flex-wrap: wrap;">
<div style="flex: 1; min-width: 140px;">
<div class="arch-layer user">
<div class="arch-layer-title">입력</div>
<div class="arch-box" style="margin-bottom: 6px;">L1 이미지/PDF<br/>페이지 단위</div>
<div class="arch-box">L3 LayoutBlock<br/>영역 · 읽기순서 · block_type</div>
</div>
</div>
<div style="display: flex; align-items: center; font-size: 16px; color: #78350f;">→</div>
<div style="flex: 1; min-width: 140px;">
<div class="arch-layer application">
<div class="arch-layer-title">OCR 레지스트리 (registry.py)</div>
<div class="arch-box highlight">자동 등록<br/>우선순위 기반 선택<br/>엔진 불가시 폴백</div>
</div>
</div>
<div style="display: flex; align-items: center; font-size: 16px; color: #78350f;">→</div>
<div style="flex: 1.2; min-width: 160px;">
<div class="arch-layer ai">
<div class="arch-layer-title">OCR 엔진 (우선순위순)</div>
<div class="arch-box" style="margin: 3px 0;"><b>1.</b> NDL古典籍OCR Full<br/><i>TrOCR · RTMDet · GPU 권장</i></div>
<div class="arch-box" style="margin: 3px 0;"><b>2.</b> NDL古典籍OCR-Lite<br/><i>ONNX 경량 · CPU 가능</i></div>
<div class="arch-box" style="margin: 3px 0;"><b>3.</b> NDLOCR-Lite<br/><i>현대/인쇄 · ParseQ · DEIM</i></div>
<div class="arch-box" style="margin: 3px 0;"><b>4.</b> LLM Vision OCR<br/><i>LLM 비전 모델 활용</i></div>
<div class="arch-box" style="margin: 3px 0;"><b>5.</b> PaddleOCR<br/><i>다국어 · 멀티라인</i></div>
</div>
</div>
<div style="display: flex; align-items: center; font-size: 16px; color: #78350f;">→</div>
<div style="flex: 1; min-width: 140px;">
<div class="arch-layer data">
<div class="arch-layer-title">파이프라인 (pipeline.py)</div>
<div class="arch-box" style="margin: 3px 0;">이미지 크롭<br/>(LayoutBlock bbox)</div>
<div style="text-align: center; font-size: 10px; color: #065f46;">↓</div>
<div class="arch-box" style="margin: 3px 0;">전처리<br/>(BGR/RGB · 리사이즈)</div>
<div style="text-align: center; font-size: 10px; color: #065f46;">↓</div>
<div class="arch-box" style="margin: 3px 0;">글자 인식<br/>(엔진별 추론)</div>
<div style="text-align: center; font-size: 10px; color: #065f46;">↓</div>
<div class="arch-box" style="margin: 3px 0;">후처리<br/>(신뢰도 필터 · 좌표 매핑)</div>
</div>
</div>
<div style="display: flex; align-items: center; font-size: 16px; color: #78350f;">→</div>
<div style="flex: 1; min-width: 140px;">
<div class="arch-layer" style="background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626;">
<div class="arch-layer-title" style="color: #991b1b;">출력</div>
<div class="arch-box highlight">L2 OcrResult<br/>ocr_page.json</div>
<div class="arch-box" style="margin-top: 6px;">OcrLine → OcrCharacter<br/>char · bbox · confidence</div>
</div>
<div class="arch-layer infra" style="margin-top: 8px;">
<div class="arch-layer-title">읽기 순서</div>
<div class="arch-box tech" style="margin: 3px 0;">XY-Cut 알고리즘</div>
<div class="arch-box tech" style="margin: 3px 0;">Smooth Ordering</div>
<div class="arch-box tech" style="margin: 3px 0;">割注 블록 감지</div>
</div>
</div>
</div>
</div>

---

## 6. 사용자 워크플로우

연구자의 작업 흐름. 자료 수집 → 원본 작업(L1-L4) → 해석 작업(L5-L8) → 관리.

<div style="max-width: 1200px; width: 100%; margin: 0 auto;">
<style scoped>
.arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #78350f; margin-bottom: 16px; }
.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 2px 6px rgba(120, 53, 15, 0.08); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
.arch-box { border-radius: 5px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #44220e; background: #fffcf7; border: 1px solid #d4c4a8; }.arch-box.highlight { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #b45309; }.arch-box.tech { font-size: 10px; color: #78350f; background: #f5efe6; }
.arch-layer.external { background: linear-gradient(135deg, #f5efe5 0%, #ede4d4 100%); border: 2px dashed #b8a080; }.arch-layer.external .arch-layer-title { color: #8a7a68; }.arch-layer.user { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #d97706; }.arch-layer.user .arch-layer-title { color: #92400e; }.arch-layer.application { background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c; }.arch-layer.application .arch-layer-title { color: #9a3412; }.arch-layer.ai { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626; }.arch-layer.ai .arch-layer-title { color: #991b1b; }.arch-layer.data { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 2px solid #059669; }.arch-layer.data .arch-layer-title { color: #065f46; }.arch-layer.infra { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); border: 2px solid #64748b; }.arch-layer.infra .arch-layer-title { color: #334155; }
.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f0ead8 0%, #e5dcca 100%); border: 2px solid #c4b498; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(120, 53, 15, 0.06); }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #78350f; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #44220e; background: #fffcf7; padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid #d4c4a8; }.arch-sidebar-item.metric { background: #fef3c7; border: 1px solid #d97706; color: #92400e; font-weight: 600; }
</style>
<div class="arch-title">사용자 워크플로우</div>
<div class="arch-wrapper">
<div class="arch-main">
<div class="arch-layer user">
<div class="arch-layer-title">Phase 1: 자료 수집</div>
<div class="arch-grid arch-grid-2">
<div class="arch-box">문헌 가져오기<br/>PDF/이미지 업로드 · HWP 임포트</div>
<div class="arch-box">서지정보 파싱<br/>NDL · KORCIS · Archives.JP</div>
</div>
</div>
<div style="text-align: center; font-size: 11px; color: #78350f;">↓</div>
<div class="arch-layer data">
<div class="arch-layer-title">Phase 2: 원본 작업 (L1-L4)</div>
<div class="arch-grid arch-grid-5">
<div class="arch-box">열람<br/>PDF.js 뷰어<br/>이미지 확대/축소</div>
<div class="arch-box">레이아웃 분석<br/>영역 자동감지 (LLM)<br/>수동 편집 · 읽기순서</div>
<div class="arch-box">OCR 실행<br/>엔진 선택<br/>블록별 인식</div>
<div class="arch-box">교정<br/>OCR→텍스트 대조<br/>이체자 확인 · 확정</div>
<div class="arch-box">편성<br/>LayoutBlock→TextBlock<br/>source_ref 추적</div>
</div>
<div style="text-align: center; font-size: 10px; color: #065f46; margin-top: 6px;">열람 → 레이아웃 → OCR → 교정 → 편성</div>
</div>
<div style="text-align: center; font-size: 12px; font-weight: bold; color: #ea580c;">⬇ 저장소 경계 ⬇</div>
<div class="arch-layer" style="background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%); border: 2px solid #4f46e5;">
<div class="arch-layer-title" style="color: #3730a3;">Phase 3: 해석 작업 (L5-L8)</div>
<div class="arch-grid arch-grid-5">
<div class="arch-box">표점 (L5)<br/>句讀 삽입<br/>글자 인덱스 기반</div>
<div class="arch-box">현토 (L5)<br/>懸吐 달기<br/>after/before/over/under</div>
<div class="arch-box">번역 (L6)<br/>LLM draft→사람 review<br/>사전 참조 · 주석 컨텍스트</div>
<div class="arch-box">주석 (L7)<br/>4단계 사전 생성<br/>인물/지명 자동태깅</div>
<div class="arch-box">인용마크 (L7)<br/>학술 인용 구절 지정<br/>교차 레이어 해소</div>
</div>
<div style="text-align: center; font-size: 10px; color: #3730a3; margin-top: 6px;">표점 → 현토 → 번역 → 주석 → 인용마크</div>
</div>
<div class="arch-layer infra">
<div class="arch-layer-title">Phase 4: 관리</div>
<div class="arch-grid arch-grid-4">
<div class="arch-box">Git 이력<br/>커밋 · diff · 되돌리기</div>
<div class="arch-box">스냅샷<br/>JSON 내보내기/가져오기</div>
<div class="arch-box">이체자 정렬<br/>일괄 교정</div>
<div class="arch-box">이체자 사전<br/>variant_chars.json</div>
</div>
</div>
</div>
<div class="arch-sidebar">
<div class="arch-sidebar-panel">
<div class="arch-sidebar-title">LLM 협업 패턴<br/>(2-8층 공통)</div>
<div class="arch-sidebar-item metric">LLM이 draft 생성</div>
<div class="arch-sidebar-item">↓</div>
<div class="arch-sidebar-item metric">사람이 review</div>
<div class="arch-sidebar-item">↓</div>
<div class="arch-sidebar-item metric">사람이 commit<br/>(Git 자동 저장)</div>
</div>
</div>
</div>
</div>

---

## 7. 스키마 간 참조 관계도

19개 스키마(원본 7 + 해석 5 + 코어 6 + 교환 1)의 연결 구조.
화살표는 참조 방향: A → B = "A가 B를 참조".

<div style="max-width: 1200px; width: 100%; margin: 0 auto;">
<style scoped>
.arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #78350f; margin-bottom: 16px; }
.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 2px 6px rgba(120, 53, 15, 0.08); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
.arch-box { border-radius: 5px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #44220e; background: #fffcf7; border: 1px solid #d4c4a8; }.arch-box.highlight { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #b45309; }.arch-box.tech { font-size: 10px; color: #78350f; background: #f5efe6; }
.arch-layer.external { background: linear-gradient(135deg, #f5efe5 0%, #ede4d4 100%); border: 2px dashed #b8a080; }.arch-layer.external .arch-layer-title { color: #8a7a68; }.arch-layer.user { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #d97706; }.arch-layer.user .arch-layer-title { color: #92400e; }.arch-layer.application { background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c; }.arch-layer.application .arch-layer-title { color: #9a3412; }.arch-layer.ai { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626; }.arch-layer.ai .arch-layer-title { color: #991b1b; }.arch-layer.data { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 2px solid #059669; }.arch-layer.data .arch-layer-title { color: #065f46; }.arch-layer.infra { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); border: 2px solid #64748b; }.arch-layer.infra .arch-layer-title { color: #334155; }
.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f0ead8 0%, #e5dcca 100%); border: 2px solid #c4b498; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(120, 53, 15, 0.06); }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #78350f; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #44220e; background: #fffcf7; padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid #d4c4a8; }.arch-sidebar-item.metric { background: #fef3c7; border: 1px solid #d97706; color: #92400e; font-weight: 600; }
</style>
<div class="arch-title">스키마 간 참조 관계도</div>
<div class="arch-grid arch-grid-2">
<div class="arch-layer application">
<div class="arch-layer-title">원본 저장소 스키마 (7개)</div>
<div class="arch-box highlight" style="margin: 4px 0;">manifest<br/><i>document_id, parts, completeness_status</i></div>
<div class="arch-box" style="margin: 4px 0;">bibliography<br/><i>서지정보, raw_metadata, _mapping_info</i></div>
<div class="arch-box" style="margin: 4px 0;">ocr_page<br/><i>OcrResult · char, bbox, confidence</i></div>
<div class="arch-box" style="margin: 4px 0;">layout_page<br/><i>LayoutBlock · block_id, bbox, reading_order</i></div>
<div class="arch-box" style="margin: 4px 0;">corrections<br/><i>Correction · type, original_ocr, corrected</i></div>
<div class="arch-box" style="margin: 4px 0;">interp_manifest<br/><i>interpretation_id, source_document_id</i></div>
<div class="arch-box" style="margin: 4px 0;">dependency<br/><i>source.base_commit, tracked_files, status</i></div>
</div>
<div class="arch-layer" style="background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%); border: 2px solid #4f46e5;">
<div class="arch-layer-title" style="color: #3730a3;">해석 저장소 스키마 (5개)</div>
<div class="arch-box" style="margin: 4px 0;">punctuation_page<br/><i>block_id, marks, target, before/after</i></div>
<div class="arch-box" style="margin: 4px 0;">hyeonto_page<br/><i>block_id, annotations, position, text</i></div>
<div class="arch-box" style="margin: 4px 0;">translation_page<br/><i>source, translations, status, annotation_context</i></div>
<div class="arch-box" style="margin: 4px 0;">annotation_page v2<br/><i>blocks, annotations, dictionary, generation_history</i></div>
<div class="arch-box" style="margin: 4px 0;">citation_mark_page<br/><i>marks, source, marked_from, citation_override</i></div>
</div>
<div class="arch-layer" style="background: linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%); border: 2px solid #7c3aed;">
<div class="arch-layer-title" style="color: #5b21b6;">코어 스키마 (6개)</div>
<div class="arch-box" style="margin: 4px 0;">Work<br/><i>title, author, period</i></div>
<div class="arch-box" style="margin: 4px 0;">TextBlock<br/><i>work_id, original_text, source_ref</i></div>
<div class="arch-box" style="margin: 4px 0;">Tag<br/><i>block_id, surface, core_category</i></div>
<div class="arch-box" style="margin: 4px 0;">Concept<br/><i>label, concept_features</i></div>
<div class="arch-box" style="margin: 4px 0;">Agent<br/><i>name, period</i></div>
<div class="arch-box" style="margin: 4px 0;">Relation<br/><i>subject, predicate, object, evidence_blocks</i></div>
</div>
<div class="arch-layer data">
<div class="arch-layer-title">교환 형식 (1개)</div>
<div class="arch-box highlight">exchange<br/><i>단일 JSON 스냅샷 · 내보내기/가져오기</i></div>
</div>
</div>
<div style="margin-top: 10px; padding: 10px; background: #f5efe6; border-radius: 6px; font-size: 10px; color: #44220e; line-height: 1.6;">
<b>참조 방향:</b><br/>
layout_page/ocr_page → manifest (part_id) &nbsp;|&nbsp; ocr_page/corrections → layout_page (layout_block_id/block_id)<br/>
interp_manifest/dependency → manifest (document_id + base_commit)<br/>
모든 해석 스키마 → layout_page (block_id) &nbsp;|&nbsp; translation_page ↔ annotation_page (annotation_context)<br/>
TextBlock → Work (work_id) &nbsp;|&nbsp; Tag → TextBlock (block_id) &nbsp;|&nbsp; Tag ⇢ Concept (승격)<br/>
Relation → Agent/Concept (subject_id) &nbsp;|&nbsp; Relation → TextBlock (evidence_blocks)<br/>
TextBlock ⇢ manifest (source_ref 역참조)
</div>
</div>

**참조 패턴 요약:**
- 원본 내부: `layout_page/ocr_page` → `manifest`, `ocr_page/corrections` → `layout_page`
- 저장소 간: `interp_manifest/dependency` → `manifest` (document_id + base_commit)
- 해석→원본: 모든 해석 스키마 → `layout_page` (block_id로 연결)
- 해석 내부: `translation_page` ↔ `annotation_page` (annotation_context)
- 코어→원본: `TextBlock.source_ref` → `manifest` (역참조)

---

## 8. 백엔드 모듈 의존 구조

`server.py`(조립) → 8개 라우터 → `_state.py`(공유 상태) → core/llm/ocr 모듈.
라우터 간 직접 import 금지. `_state.py`가 lazy import로 순환 방지.

<div style="max-width: 1200px; width: 100%; margin: 0 auto;">
<style scoped>
.arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #78350f; margin-bottom: 16px; }
.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 2px 6px rgba(120, 53, 15, 0.08); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
.arch-box { border-radius: 5px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #44220e; background: #fffcf7; border: 1px solid #d4c4a8; }.arch-box.highlight { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #b45309; }.arch-box.tech { font-size: 10px; color: #78350f; background: #f5efe6; }
.arch-layer.external { background: linear-gradient(135deg, #f5efe5 0%, #ede4d4 100%); border: 2px dashed #b8a080; }.arch-layer.external .arch-layer-title { color: #8a7a68; }.arch-layer.user { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #d97706; }.arch-layer.user .arch-layer-title { color: #92400e; }.arch-layer.application { background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c; }.arch-layer.application .arch-layer-title { color: #9a3412; }.arch-layer.ai { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626; }.arch-layer.ai .arch-layer-title { color: #991b1b; }.arch-layer.data { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 2px solid #059669; }.arch-layer.data .arch-layer-title { color: #065f46; }.arch-layer.infra { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); border: 2px solid #64748b; }.arch-layer.infra .arch-layer-title { color: #334155; }
.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f0ead8 0%, #e5dcca 100%); border: 2px solid #c4b498; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(120, 53, 15, 0.06); }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #78350f; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #44220e; background: #fffcf7; padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid #d4c4a8; }.arch-sidebar-item.metric { background: #fef3c7; border: 1px solid #d97706; color: #92400e; font-weight: 600; }
</style>
<div class="arch-title">백엔드 모듈 의존 구조</div>
<div class="arch-layer application">
<div class="arch-layer-title">src/app/ — API 레이어</div>
<div class="arch-grid arch-grid-3" style="margin-bottom: 8px;">
<div class="arch-box">__main__.py<br/>CLI 진입점</div>
<div class="arch-box highlight">server.py<br/>FastAPI 앱 생성 · 라우터 마운트</div>
<div class="arch-box highlight">_state.py<br/>공유 상태, 헬퍼 · LLM 캐시, 토큰 계산</div>
</div>
<div style="font-size: 10px; font-weight: 600; color: #9a3412; margin-bottom: 4px; text-align: center;">routers/ — 8개 도메인</div>
<div class="arch-grid arch-grid-4">
<div class="arch-box">library <b>15</b></div>
<div class="arch-box">documents <b>32</b></div>
<div class="arch-box">interpretations <b>22</b></div>
<div class="arch-box">llm_ocr <b>13</b></div>
<div class="arch-box">alignment <b>17</b></div>
<div class="arch-box">reading <b>24</b></div>
<div class="arch-box">annotation <b>32</b></div>
<div class="arch-box">version <b>7</b></div>
</div>
<div style="text-align: center; font-size: 10px; color: #9a3412; margin-top: 6px;">__main__ → server → include_router → 8 routers → _state</div>
</div>
<div style="text-align: center; font-size: 11px; color: #78350f;">↓ lazy import</div>
<div class="arch-grid arch-grid-3">
<div class="arch-layer data">
<div class="arch-layer-title">src/core/ — 비즈니스 로직</div>
<div class="arch-box" style="margin: 3px 0;">library</div>
<div class="arch-box" style="margin: 3px 0;">document</div>
<div class="arch-box" style="margin: 3px 0;">interpretation</div>
<div class="arch-box" style="margin: 3px 0;">entity</div>
<div class="arch-box" style="margin: 3px 0;">punctuation / punctuation_llm</div>
<div class="arch-box" style="margin: 3px 0;">hyeonto</div>
<div class="arch-box" style="margin: 3px 0;">translation / translation_llm</div>
<div class="arch-box" style="margin: 3px 0;">annotation / annotation_llm<br/>annotation_dict_llm / annotation_dict_match</div>
<div class="arch-box" style="margin: 3px 0;">citation_mark</div>
<div class="arch-box" style="margin: 3px 0;">alignment</div>
<div class="arch-box" style="margin: 3px 0;">git_graph</div>
<div class="arch-box" style="margin: 3px 0;">snapshot / snapshot_validator</div>
<div class="arch-box" style="margin: 3px 0;">backup</div>
<div class="arch-box" style="margin: 3px 0;">layout_analyzer</div>
</div>
<div class="arch-layer" style="background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c;">
<div class="arch-layer-title" style="color: #9a3412;">src/llm/ — LLM 통합</div>
<div class="arch-box highlight" style="margin: 3px 0;">router.py — 4단 폴백</div>
<div class="arch-box" style="margin: 3px 0;">config.py</div>
<div class="arch-box" style="margin: 3px 0;">draft.py</div>
<div class="arch-box" style="margin: 3px 0;">usage_tracker.py</div>
<div style="font-size: 10px; font-weight: 600; color: #9a3412; margin: 6px 0 4px; text-align: center;">providers/</div>
<div class="arch-box tech" style="margin: 3px 0;">base44_bridge</div>
<div class="arch-box tech" style="margin: 3px 0;">ollama</div>
<div class="arch-box tech" style="margin: 3px 0;">openai</div>
<div class="arch-box tech" style="margin: 3px 0;">anthropic</div>
<div class="arch-box tech" style="margin: 3px 0;">gemini</div>
</div>
<div>
<div class="arch-layer ai">
<div class="arch-layer-title">src/ocr/ — OCR 엔진</div>
<div class="arch-box" style="margin: 3px 0;">registry.py</div>
<div class="arch-box" style="margin: 3px 0;">pipeline.py</div>
<div class="arch-box tech" style="margin: 3px 0;">ndlkotenocr_full</div>
<div class="arch-box tech" style="margin: 3px 0;">ndlkotenocr_lite</div>
<div class="arch-box tech" style="margin: 3px 0;">ndlocr_lite</div>
<div class="arch-box tech" style="margin: 3px 0;">llm_ocr</div>
<div class="arch-box tech" style="margin: 3px 0;">paddleocr</div>
</div>
<div class="arch-layer infra">
<div class="arch-layer-title">기타 모듈</div>
<div class="arch-box" style="margin: 3px 0;">src/parsers/<br/>ndl, korcis, archives_jp</div>
<div class="arch-box" style="margin: 3px 0;">src/hwp/<br/>reader, text_cleaner</div>
<div class="arch-box" style="margin: 3px 0;">src/text_import/<br/>pdf_extractor</div>
<div class="arch-box" style="margin: 3px 0;">src/cli/</div>
</div>
</div>
</div>
<div style="text-align: center; font-size: 10px; color: #78350f; margin-top: 8px;">core → llm &nbsp;|&nbsp; core → ocr</div>
</div>

**규칙:**
- 라우터 간 직접 import 금지 → 공유 로직은 `_state.py`에 배치
- `_state.py`는 core/llm/ocr 모듈을 lazy import (순환 방지)
- Pydantic 모델은 사용하는 라우터 파일 내부에 정의

---

## 9. Git 저장소 모델

하나의 원본 저장소 위에 여러 해석 저장소가 독립 Git 리포로 병존.
`library_manifest.json`이 서고 전체 지도 역할.

<div style="max-width: 1200px; width: 100%; margin: 0 auto;">
<style scoped>
.arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #78350f; margin-bottom: 16px; }
.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 2px 6px rgba(120, 53, 15, 0.08); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
.arch-box { border-radius: 5px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #44220e; background: #fffcf7; border: 1px solid #d4c4a8; }.arch-box.highlight { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #b45309; }.arch-box.tech { font-size: 10px; color: #78350f; background: #f5efe6; }
.arch-layer.external { background: linear-gradient(135deg, #f5efe5 0%, #ede4d4 100%); border: 2px dashed #b8a080; }.arch-layer.external .arch-layer-title { color: #8a7a68; }.arch-layer.user { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #d97706; }.arch-layer.user .arch-layer-title { color: #92400e; }.arch-layer.application { background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c; }.arch-layer.application .arch-layer-title { color: #9a3412; }.arch-layer.ai { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626; }.arch-layer.ai .arch-layer-title { color: #991b1b; }.arch-layer.data { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 2px solid #059669; }.arch-layer.data .arch-layer-title { color: #065f46; }.arch-layer.infra { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); border: 2px solid #64748b; }.arch-layer.infra .arch-layer-title { color: #334155; }
.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f0ead8 0%, #e5dcca 100%); border: 2px solid #c4b498; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(120, 53, 15, 0.06); }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #78350f; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #44220e; background: #fffcf7; padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid #d4c4a8; }.arch-sidebar-item.metric { background: #fef3c7; border: 1px solid #d97706; color: #92400e; font-weight: 600; }
</style>
<div class="arch-title">Git 저장소 모델</div>
<div class="arch-grid arch-grid-2">
<div>
<div class="arch-layer user">
<div class="arch-layer-title">서고 (library_manifest.json)</div>
<div class="arch-box highlight">library_manifest.json<br/>서고 전체 지도 · 문헌 목록, 해석 목록</div>
</div>
<div class="arch-layer data">
<div class="arch-layer-title">원본 저장소 (Git repo)</div>
<div class="arch-grid arch-grid-2">
<div class="arch-box">manifest.json<br/>document_id, parts</div>
<div class="arch-box highlight">L1_source/<br/>PDF, 이미지 (불변)</div>
<div class="arch-box">L2_ocr/<br/>ocr_page JSON</div>
<div class="arch-box">L3_layout/<br/>layout_page JSON</div>
<div class="arch-box">L4_text/<br/>corrections JSON</div>
<div class="arch-box">bibliography.json</div>
</div>
<div class="arch-box tech" style="margin-top: 6px;">Git 이력: commit, diff, log</div>
</div>
<div class="arch-layer external">
<div class="arch-layer-title">원격 호스팅 (선택)</div>
<div class="arch-box">GitHub / GitLab / Gitea<br/>← push/pull →</div>
</div>
</div>
<div>
<div class="arch-layer" style="background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%); border: 2px solid #4f46e5;">
<div class="arch-layer-title" style="color: #3730a3;">해석 A (연구자 김, Git repo)</div>
<div class="arch-box" style="margin: 3px 0;">interp_manifest.json — interpreter: 김</div>
<div class="arch-box highlight" style="margin: 3px 0;">dependency.json — base_commit 추적</div>
<div class="arch-grid arch-grid-3" style="margin-top: 4px;">
<div class="arch-box">L5/<br/>punctuation, hyeonto</div>
<div class="arch-box">L6/<br/>translation</div>
<div class="arch-box">L7/<br/>annotation, citation</div>
</div>
<div class="arch-box tech" style="margin-top: 4px;">core/ — Work, TextBlock, Tag, Concept, Agent, Relation</div>
</div>
<div class="arch-layer" style="background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%); border: 1px solid #6366f1;">
<div class="arch-layer-title" style="color: #4338ca;">해석 B (LLM draft, Git repo)</div>
<div class="arch-box" style="margin: 3px 0;">interp_manifest.json — interpreter: LLM</div>
<div class="arch-box" style="margin: 3px 0;">dependency.json</div>
<div class="arch-grid arch-grid-2" style="margin-top: 4px;">
<div class="arch-box tech">L5/</div>
<div class="arch-box tech">L6/ LLM 번역</div>
</div>
</div>
<div class="arch-layer" style="background: linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%); border: 1px solid #7c3aed;">
<div class="arch-layer-title" style="color: #5b21b6;">해석 C (공동연구, Git repo)</div>
<div class="arch-box" style="margin: 3px 0;">interp_manifest.json — interpreter: 팀</div>
<div class="arch-box" style="margin: 3px 0;">dependency.json</div>
<div class="arch-grid arch-grid-3" style="margin-top: 4px;">
<div class="arch-box tech">L5/</div>
<div class="arch-box tech">L6/</div>
<div class="arch-box tech">L7/</div>
</div>
</div>
</div>
</div>
<div style="text-align: center; font-size: 10px; color: #78350f; margin-top: 8px;">
library_manifest → 원본 저장소 / 해석 A, B, C &nbsp;|&nbsp; 각 dependency.json → 원본 저장소 (base_commit) &nbsp;|&nbsp; 모든 저장소 ↔ GitHub/GitLab (push/pull)
</div>
</div>

---

## 10. 층별 의존 관계

하위층 변경이 상위층에 미치는 영향. `dependency.json`의 `dependency_status` 상태 전이.

<div style="max-width: 1200px; width: 100%; margin: 0 auto;">
<style scoped>
.arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #78350f; margin-bottom: 16px; }
.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 2px 6px rgba(120, 53, 15, 0.08); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
.arch-box { border-radius: 5px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #44220e; background: #fffcf7; border: 1px solid #d4c4a8; }.arch-box.highlight { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #b45309; }.arch-box.tech { font-size: 10px; color: #78350f; background: #f5efe6; }
.arch-layer.external { background: linear-gradient(135deg, #f5efe5 0%, #ede4d4 100%); border: 2px dashed #b8a080; }.arch-layer.external .arch-layer-title { color: #8a7a68; }.arch-layer.user { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #d97706; }.arch-layer.user .arch-layer-title { color: #92400e; }.arch-layer.application { background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c; }.arch-layer.application .arch-layer-title { color: #9a3412; }.arch-layer.ai { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626; }.arch-layer.ai .arch-layer-title { color: #991b1b; }.arch-layer.data { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 2px solid #059669; }.arch-layer.data .arch-layer-title { color: #065f46; }.arch-layer.infra { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); border: 2px solid #64748b; }.arch-layer.infra .arch-layer-title { color: #334155; }
.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f0ead8 0%, #e5dcca 100%); border: 2px solid #c4b498; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(120, 53, 15, 0.06); }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #78350f; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #44220e; background: #fffcf7; padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid #d4c4a8; }.arch-sidebar-item.metric { background: #fef3c7; border: 1px solid #d97706; color: #92400e; font-weight: 600; }
</style>
<div class="arch-title">층별 의존 관계</div>
<div style="display: flex; gap: 10px; align-items: stretch; flex-wrap: wrap;">
<div style="flex: 1; min-width: 180px;">
<div class="arch-layer data">
<div class="arch-layer-title">원본 저장소 내부</div>
<div class="arch-box" style="margin: 4px 0;">L1 이미지 (불변)</div>
<div style="text-align: center; font-size: 10px; color: #065f46;">↓ 거의 없음</div>
<div class="arch-box" style="margin: 4px 0;">L2 OCR</div>
<div style="text-align: center; font-size: 10px; color: #065f46;">↓ OCR 재실행 필요</div>
<div class="arch-box" style="margin: 4px 0;">L3 레이아웃</div>
<div style="text-align: center; font-size: 10px; color: #065f46;">↓ 블록 재분류 필요</div>
<div class="arch-box" style="margin: 4px 0;">L4 교정</div>
</div>
</div>
<div style="display: flex; align-items: center; font-size: 18px; font-weight: bold; color: #ea580c;">⇒</div>
<div style="flex: 0.8; min-width: 160px;">
<div class="arch-layer application">
<div class="arch-layer-title">저장소 경계</div>
<div class="arch-box highlight">경고 발생<br/>dependency.json<br/>tracked_files hash 비교</div>
<div style="text-align: center; font-size: 10px; color: #9a3412; margin-top: 4px;">모든 해석에 경고 전파</div>
</div>
</div>
<div style="display: flex; align-items: center; font-size: 18px; font-weight: bold; color: #ea580c;">⇒</div>
<div style="flex: 1; min-width: 180px;">
<div class="arch-layer" style="background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%); border: 2px solid #4f46e5;">
<div class="arch-layer-title" style="color: #3730a3;">해석 저장소 내부</div>
<div class="arch-box" style="margin: 4px 0;">L5 표점/현토</div>
<div style="text-align: center; font-size: 10px; color: #3730a3;">↓ 표점 변경시 번역 재검토</div>
<div class="arch-box" style="margin: 4px 0;">L6 번역</div>
<div style="text-align: center; font-size: 10px; color: #3730a3;">↓ 번역 변경시 주석 재검토</div>
<div class="arch-box" style="margin: 4px 0;">L7 주석</div>
<div style="text-align: center; font-size: 10px; color: #3730a3;">↓ 주석 변경시</div>
<div class="arch-box" style="margin: 4px 0;">L8 외부연계</div>
</div>
</div>
<div style="display: flex; align-items: center; font-size: 12px; color: #78350f;">|</div>
<div style="flex: 0.8; min-width: 150px;">
<div class="arch-layer infra">
<div class="arch-layer-title">dependency_status 상태</div>
<div class="arch-box highlight" style="margin: 4px 0;">synced<br/>일치</div>
<div style="text-align: center; font-size: 10px; color: #334155;">↓</div>
<div class="arch-box" style="margin: 4px 0; background: #fee2e2; border-color: #dc2626;">stale<br/>변경 감지</div>
<div style="text-align: center; font-size: 10px; color: #334155;">↓</div>
<div class="arch-box" style="margin: 4px 0; background: #fef3c7; border-color: #d97706;">acknowledged<br/>확인 완료</div>
<div style="text-align: center; font-size: 10px; color: #334155;">↓ (다시 synced)</div>
</div>
</div>
</div>
</div>

---

## 11. 프론트엔드 UI 구조

VSCode 스타일 3패널 레이아웃. 왼쪽(탐색) · 가운데(PDF 뷰어) · 오른쪽(작업 탭).

<div style="max-width: 1200px; width: 100%; margin: 0 auto;">
<style scoped>
.arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #78350f; margin-bottom: 16px; }
.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 2px 6px rgba(120, 53, 15, 0.08); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
.arch-box { border-radius: 5px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #44220e; background: #fffcf7; border: 1px solid #d4c4a8; }.arch-box.highlight { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #b45309; }.arch-box.tech { font-size: 10px; color: #78350f; background: #f5efe6; }
.arch-layer.external { background: linear-gradient(135deg, #f5efe5 0%, #ede4d4 100%); border: 2px dashed #b8a080; }.arch-layer.external .arch-layer-title { color: #8a7a68; }.arch-layer.user { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #d97706; }.arch-layer.user .arch-layer-title { color: #92400e; }.arch-layer.application { background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c; }.arch-layer.application .arch-layer-title { color: #9a3412; }.arch-layer.ai { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626; }.arch-layer.ai .arch-layer-title { color: #991b1b; }.arch-layer.data { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 2px solid #059669; }.arch-layer.data .arch-layer-title { color: #065f46; }.arch-layer.infra { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); border: 2px solid #64748b; }.arch-layer.infra .arch-layer-title { color: #334155; }
.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f0ead8 0%, #e5dcca 100%); border: 2px solid #c4b498; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(120, 53, 15, 0.06); }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #78350f; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #44220e; background: #fffcf7; padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid #d4c4a8; }.arch-sidebar-item.metric { background: #fef3c7; border: 1px solid #d97706; color: #92400e; font-weight: 600; }
</style>
<div class="arch-title">프론트엔드 UI 구조</div>
<div class="arch-layer user">
<div class="arch-layer-title">VSCode 스타일 3패널 레이아웃</div>
<div style="display: flex; gap: 8px;">
<div style="flex: 0.8; min-width: 140px;">
<div class="arch-layer data" style="margin: 0; height: 100%;">
<div class="arch-layer-title">왼쪽: 액티비티 바 + 사이드바</div>
<div class="arch-box" style="margin: 4px 0;">액티비티 바<br/>8개 패널 전환</div>
<div class="arch-box" style="margin: 4px 0;">sidebar-tree.js<br/>문헌 목록 · 권/페이지 트리</div>
<div class="arch-box" style="margin: 4px 0;">interpretation.js<br/>해석 저장소 목록 · 생성/선택/삭제</div>
</div>
</div>
<div style="flex: 1; min-width: 160px;">
<div class="arch-layer application" style="margin: 0; height: 100%;">
<div class="arch-layer-title">가운데: PDF/이미지 뷰어</div>
<div class="arch-box highlight" style="margin: 4px 0;">pdf-renderer.js<br/>PDF.js 통합 · 확대/축소/회전</div>
<div class="arch-box" style="margin: 4px 0;">layout-editor.js<br/>LayoutBlock 오버레이 · 영역 편집/읽기순서</div>
</div>
</div>
<div style="flex: 1.2; min-width: 180px;">
<div class="arch-layer" style="background: linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%); border: 2px solid #7c3aed; margin: 0; height: 100%;">
<div class="arch-layer-title" style="color: #5b21b6;">오른쪽: 작업 패널 (탭 전환)</div>
<div class="arch-box" style="margin: 3px 0;">교정 탭 — correction-editor.js<br/>OCR vs 교정 텍스트</div>
<div class="arch-box" style="margin: 3px 0;">표점 탭 — punctuation-editor.js<br/>구두점 삽입</div>
<div class="arch-box" style="margin: 3px 0;">현토 탭 — hyeonto-editor.js<br/>懸吐 달기</div>
<div class="arch-box" style="margin: 3px 0;">번역 탭 — translation-editor.js<br/>LLM draft + 편집</div>
<div class="arch-box" style="margin: 3px 0;">주석 탭 — annotation-editor.js<br/>사전형 주석 + 태깅</div>
<div class="arch-box" style="margin: 3px 0;">인용 탭 — citation-editor.js<br/>학술 인용 마크</div>
<div class="arch-box" style="margin: 3px 0;">비고 탭 — notes-panel.js<br/>페이지별 메모</div>
</div>
</div>
</div>
</div>
<div class="arch-layer infra">
<div class="arch-layer-title">하단/팝업</div>
<div class="arch-grid arch-grid-4">
<div class="arch-box tech">toast.js<br/>알림</div>
<div class="arch-box tech">ocr-panel.js<br/>OCR 엔진 선택/실행</div>
<div class="arch-box tech">git-graph.js<br/>커밋 이력/diff</div>
<div class="arch-box tech">bibliography.js<br/>서지정보 편집</div>
<div class="arch-box tech">alignment-view.js<br/>이체자 정렬</div>
<div class="arch-box tech">entity-manager.js<br/>코어 엔티티 관리</div>
<div class="arch-box tech">hwp-import.js<br/>HWP 가져오기</div>
<div class="arch-box tech">batch-correction.js<br/>일괄 교정</div>
</div>
</div>
</div>

---

## 12. L7 주석 4단계 누적 생성 워크플로우

annotation_page v2의 4단계 `current_stage` 전이. 각 단계마다 `generation_history`에 스냅샷 저장.

<div style="max-width: 1200px; width: 100%; margin: 0 auto;">
<style scoped>
.arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #78350f; margin-bottom: 16px; }
.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 2px 6px rgba(120, 53, 15, 0.08); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
.arch-box { border-radius: 5px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #44220e; background: #fffcf7; border: 1px solid #d4c4a8; }.arch-box.highlight { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #b45309; }.arch-box.tech { font-size: 10px; color: #78350f; background: #f5efe6; }
.arch-layer.external { background: linear-gradient(135deg, #f5efe5 0%, #ede4d4 100%); border: 2px dashed #b8a080; }.arch-layer.external .arch-layer-title { color: #8a7a68; }.arch-layer.user { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #d97706; }.arch-layer.user .arch-layer-title { color: #92400e; }.arch-layer.application { background: linear-gradient(135deg, #ffedd5 0%, #fdba74 100%); border: 2px solid #ea580c; }.arch-layer.application .arch-layer-title { color: #9a3412; }.arch-layer.ai { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border: 2px solid #dc2626; }.arch-layer.ai .arch-layer-title { color: #991b1b; }.arch-layer.data { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 2px solid #059669; }.arch-layer.data .arch-layer-title { color: #065f46; }.arch-layer.infra { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); border: 2px solid #64748b; }.arch-layer.infra .arch-layer-title { color: #334155; }
.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f0ead8 0%, #e5dcca 100%); border: 2px solid #c4b498; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(120, 53, 15, 0.06); }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #78350f; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #44220e; background: #fffcf7; padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid #d4c4a8; }.arch-sidebar-item.metric { background: #fef3c7; border: 1px solid #d97706; color: #92400e; font-weight: 600; }
</style>
<div class="arch-title">L7 주석 4단계 누적 생성 워크플로우</div>
<div class="arch-wrapper">
<div class="arch-main">
<div class="arch-layer application">
<div class="arch-layer-title">Stage 1: from_original</div>
<div class="arch-grid arch-grid-3">
<div class="arch-box">L4 교정 텍스트<br/>(원문)</div>
<div class="arch-box highlight">LLM 분석<br/>인물/지명/용어 추출</div>
<div class="arch-box">기본 주석 생성<br/>type, label, description</div>
</div>
</div>
<div style="text-align: center; font-size: 11px; color: #78350f;">↓ Stage 1 스냅샷 저장</div>
<div class="arch-layer" style="background: linear-gradient(135deg, #e0f2fe 0%, #bae6fd 100%); border: 2px solid #0284c7;">
<div class="arch-layer-title" style="color: #0c4a6e;">Stage 2: from_translation</div>
<div class="arch-grid arch-grid-3">
<div class="arch-box">L6 번역문<br/>(현대어)</div>
<div class="arch-box highlight">LLM 보강<br/>번역 맥락 반영</div>
<div class="arch-box">사전 의미 보강<br/>dict_meaning, ctx_meaning</div>
</div>
</div>
<div style="text-align: center; font-size: 11px; color: #78350f;">↓ Stage 2 스냅샷 저장</div>
<div class="arch-layer" style="background: linear-gradient(135deg, #ccfbf1 0%, #99f6e4 100%); border: 2px solid #0d9488;">
<div class="arch-layer-title" style="color: #134e4a;">Stage 3: from_both</div>
<div class="arch-grid arch-grid-3">
<div class="arch-box">원문 + 번역<br/>(양쪽 참조)</div>
<div class="arch-box highlight">LLM 교차 검증<br/>누락 보완</div>
<div class="arch-box">교차 검증 완료<br/>sources, related 추가</div>
</div>
</div>
<div style="text-align: center; font-size: 11px; color: #78350f;">↓ Stage 3 스냅샷 저장</div>
<div class="arch-layer data">
<div class="arch-layer-title">Stage 4: reviewed</div>
<div class="arch-grid arch-grid-3">
<div class="arch-box">연구자 검토</div>
<div class="arch-box highlight">수동 편집<br/>추가/삭제/수정</div>
<div class="arch-box" style="background: linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%); border: 2px solid #059669;">최종 확정<br/>status: accepted</div>
</div>
</div>
</div>
<div class="arch-sidebar">
<div class="arch-sidebar-panel">
<div class="arch-sidebar-title">사전형 주석<br/>(DictionaryEntry)</div>
<div class="arch-sidebar-item metric">headword: 표제어</div>
<div class="arch-sidebar-item">reading: 독음</div>
<div class="arch-sidebar-item">dict_meaning: 사전 의미</div>
<div class="arch-sidebar-item">ctx_meaning: 문맥 의미</div>
<div class="arch-sidebar-item">sources: 출처</div>
<div class="arch-sidebar-item">related: 관련 항목</div>
</div>
<div class="arch-sidebar-panel">
<div class="arch-sidebar-title">generation_history</div>
<div class="arch-sidebar-item">Stage 1 스냅샷</div>
<div class="arch-sidebar-item">Stage 2 스냅샷</div>
<div class="arch-sidebar-item">Stage 3 스냅샷</div>
</div>
</div>
</div>
</div>

---

## 부록: 설계 원칙 요약

| 원칙 | 설명 |
|------|------|
| **원본 불변** | L1 파일, raw_metadata, original_text — 수정 금지 |
| **모든 필드 Nullable** | 소스에 없는 필드는 비워두고 나중에 채운다 |
| **삭제 금지, 상태 전이만** | `draft → active → deprecated → archived` |
| **원문 비변형** | 표점/현토/번역은 글자 인덱스 오버레이. 원문은 그대로 |
| **매핑 투명성** | `_mapping_info`에 출처/신뢰도 기록 |
| **출처 추적** | `source_ref`로 원본 저장소 역참조 |
| **온톨로지 비강제** | Concept 자유 확장. 부재 = 미지정 |
| **Promotion Flow** | Tag(잠정) → Concept(확정), 연구자 판단 |
| **용어 규칙** | LayoutBlock / OcrResult / TextBlock. "Block" 단독 사용 금지 |
| **오프라인 퍼스트** | 핵심 작업(교정, 열람, 커밋)은 인터넷 없이 동작 |

---

> 생성: 2026-03-14 · 12개 다이어그램 · 19개 스키마 (원본 7 + 해석 5 + 코어 6 + 교환 1) · 158 API 엔드포인트 · 27 JS 모듈
