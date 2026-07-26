# punctuation-service — 외부 표점 마이크로서비스

[yachagye/korean-classical-chinese-punctuation](https://github.com/yachagye/korean-classical-chinese-punctuation)
의 SikuRoBERTa 기반 표점 모델(F1 0.91, 7-class)을 본체(classical-text-browser)와
HTTP로 분리하여 호출하는 마이크로서비스.

## 왜 별도 서비스인가

본체는 가벼운 FastAPI + 순수 JS 환경이다. 여기에 torch/transformers/모델 가중치
(수백 MB ~ GB)를 박으면 `uv sync` 시간·디스크가 폭증하고 의존성 충돌(예: torch CPU vs
CUDA, paddlepaddle Python 충돌) 위험이 커진다. 사용자는 비개발자 인문학 연구자다.

대신 본체는 HTTP 어댑터(`force_provider == "external"`) 한 곳만 추가했다. 본체는
기본적으로 `http://127.0.0.1:8765`의 로컬 표점 서비스를 사용하고, 다른 주소의 서비스는
`EXTERNAL_PUNCT_URL` 환경변수로 덮어쓸 수 있다.

## 아키텍처

```
[브라우저]
   │  /api/llm/punctuation  (force_provider="external")
   ▼
[본체 FastAPI] ─ httpx → [punctuation-service /punctuate] → [SikuRoBERTa]
       ↑                       ↑
       │                       └─ 가중치(.ckpt) + base BERT (HF)
       └─ 기본 http://127.0.0.1:8765, 필요 시 EXTERNAL_PUNCT_URL로 위치 지정
```

본체는 응답의 `marks` 배열을 기존 정규화 함수(`_normalize_punct_marks`)로 처리하므로
LLM 표점과 동일한 UI 흐름에서 결과가 표시된다.

## 빠른 시작 — Docker (권장)

전제는 **NVIDIA GPU와 Docker Desktop**뿐이다. 베이스 이미지는 PyTorch 공식
CUDA 이미지(`pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime`)라 **누구나 그대로
빌드할 수 있다.** 처음 빌드에서 약 3.5GB를 내려받는다.

베이스를 고정하지 않고 `BASE_IMAGE`로 받는 이유: 특정 이미지를 박아 두면
그것이 없는 PC에서는 **빌드 자체가 불가능**하다. 공식 이미지를 기본으로 두고,
가진 이미지가 있으면 그것을 넘긴다.

```bash
# 이미 torch+CUDA 이미지가 있다면 재사용해 내려받기를 아낀다 (.env에 적어도 된다)
BASE_IMAGE=<그 이미지> docker compose up -d --build
```

GPU가 없다면 이 컨테이너를 쓰지 않는다 — 아래 「로컬 설치」로 CPU에서 돌릴 수
있다. 다만 **쪽마다 눈에 띄게 느리다.**

```bash
# 1. 가중치 다운로드 — yachagye 레포 README의 Google Drive 링크에서 v2.5 .ckpt 받기
#    권장 위치 예:
#    C:/Users/<USER>/Downloads/classical-text-browser-models/punctuation/v2.5_best_model_9110/...

# 2. punctuation-service 폴더에 .env 작성
cd punctuation-service
echo "PUNCT_MODEL_HOST_PATH=C:/Users/<USER>/Downloads/classical-text-browser-models/punctuation/v2.5_best_model_9110/v2.5_best_model_9110/punct-epoch=03-val_f1=0.9110.ckpt" > .env

# 3. 컨테이너 빌드 + 기동 (또는 루트의 start_server.bat 실행)
docker compose up -d --build

# 4. 상태 확인 (ready=true면 OK)
curl http://127.0.0.1:8765/health

# 5. 본체 기동
uv run python -m app serve

# 정지
docker compose down
```

`start_server.bat` / `start_server.sh`를 쓰는 경우에는 Docker Desktop을 켠 상태에서
`punctuation-service/.env` 또는 `PUNCT_MODEL_HOST_PATH`가 설정되어 있으면 Docker Compose로
표점 서비스를 자동 기동한다. 기본 URL은 본체가 자동으로 `http://127.0.0.1:8765`를 쓰므로
`EXTERNAL_PUNCT_URL`을 따로 지정할 필요가 없다. 자동 기동을 건너뛰려면 `PUNCT_AUTO_START=0`을
설정한다.

가중치 변경 시: `.env`만 수정하고 `docker compose up -d`로 재기동.

## 빠른 시작 — 로컬 설치 (옵션)

Docker를 쓰지 않을 경우. 디스크가 충분(≥3 GB)하고 토치를 직접 관리할 수 있을 때만 권장.

```bash
cd punctuation-service
uv sync --extra real    # torch+transformers+numpy 설치 (수 GB)

# 가중치 경로 + 엔진 지정 후 기동
PUNCT_ENGINE=sikurroberta \
PUNCT_MODEL_PATH=/path/to/punct_v25.ckpt \
uv run python -m punctuation_service
```

엔진 동작 확인용으로 `--extra real` 없이도 mock 엔진은 돈다:

```bash
uv sync                                 # fastapi/uvicorn만 (~30 MB)
uv run python -m punctuation_service    # PUNCT_ENGINE=mock (기본)
```

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PUNCT_HOST` | `127.0.0.1` | 바인딩 주소 (Docker에선 `0.0.0.0`로 자동 설정) |
| `PUNCT_PORT` | `8765` | 포트 |
| `PUNCT_ENGINE` | `mock` | `mock` (테스트) 또는 `sikurroberta` (실제) |
| `PUNCT_MODEL_PATH` | `""` | sikurroberta 엔진의 .ckpt 경로 (컨테이너 내부 경로) |
| `PUNCT_DEVICE` | `auto` | `auto` / `cuda` / `cpu` |

docker-compose 사용 시 호스트의 가중치 경로는 `PUNCT_MODEL_HOST_PATH`로 지정하면
컨테이너 안 `/models/checkpoint.ckpt`로 read-only 마운트된다.

## 엔드포인트

### `GET /health`

```json
{ "ok": true, "engine": "sikurroberta", "ready": true }
```

`ready=false` 의미:
- mock 엔진: 절대 발생 안 함
- sikurroberta: 가중치 파일 미발견(경로 오타 또는 미마운트)

### `POST /punctuate`

요청:
```json
{ "text": "子曰學而時習之不亦說乎有朋自遠方來不亦樂乎" }
```

응답 (mock 엔진 예시):
```json
{
  "engine": "mock",
  "punctuated": "子曰學而時習之不。亦說乎有朋自遠方。來不亦樂乎",
  "marks": [
    { "start": 7, "end": 8, "before": "", "after": "。" },
    { "start": 15, "end": 16, "before": "", "after": "。" }
  ]
}
```

`marks` 스키마는 본체 `_normalize_punct_marks()`(reading.py)와 호환되도록 맞춰져 있다.

## 본체와의 결선

본체는 기본적으로 `http://127.0.0.1:8765`를 외부 표점 서비스 주소로 사용한다.
따라서 기본 포트로 서비스를 띄운 경우에는 별도 환경변수가 필요 없다.

```bash
uv run python -m app serve
```

서비스가 다른 주소에 있으면 그때만 override한다.

```bash
EXTERNAL_PUNCT_URL=http://192.168.0.10:8765 uv run python -m app serve
```

표점 화면(L5)의 LLM 모델 드롭다운 마지막에 `● 외부 표점 서비스 (SikuRoBERTa)` 옵션이
나타난다. 외부 연동을 명시적으로 끄려면 `EXTERNAL_PUNCT_URL=off`로 실행한다.

## 엔진별 동작

### MockEngine (`PUNCT_ENGINE=mock`)
- 모델 없이 8자마다 句점(。)을 찍는 더미.
- 본체↔서비스 HTTP 계약 검증·UI 점검에만 사용. 실제 표점 정확도와 무관.

### SikuRoBERTaEngine (`PUNCT_ENGINE=sikurroberta`)
- BERT(AutoModel) backbone + Linear classifier (7-way multi-label sigmoid).
- 라벨 순서: `, 。 · ? ! 《 》` (yachagye 학습 시와 동일, 변경 금지).
- 첫 호출 시 가중치 로드 (lazy). `/health`는 파일 존재 여부만 검사하므로 가볍다.
- 토큰 한도 512에 맞춰 400자 청크로 자른 뒤 결과를 합친다.
- 베이스 BERT는 `hyper_parameters.model_name`이 가리키는 HF 모델을 자동 다운로드.
  Docker 사용 시 HuggingFace 캐시 볼륨(`punct_huggingface_cache`, 기본값)에 남으므로
  두 번째부터는 재다운로드 없음. 기존 볼륨을 재사용하려면 `.env`에 `HF_CACHE_VOLUME`을 적는다.

## 출처 표기 및 라이선스

이 서비스의 SikuRoBERTa 엔진은
[`yachagye/korean-classical-chinese-punctuation`](https://github.com/yachagye/korean-classical-chinese-punctuation)
모델과 추론 방식을 본체 HTTP 계약에 맞게 연결한 것이다. 원 저장소의 조건에 따라
원저작자와 출처를 명시하고 논문을 인용해야 한다.

- 원저작자: Junghyun Yang (양정현)
- 원 저장소: https://github.com/yachagye/korean-classical-chinese-punctuation
- 모델: Korean Classical Chinese Punctuation Prediction Model v2.5
- 라이선스: CC BY-NC-SA 4.0
- DOI: https://doi.org/10.37924/JSSW.100.9

권장 인용:

```text
Yang, J. (2025). Development and Application of a Deep Learning-Based Model
for Automated Punctuation Inference in Korean Classical Chinese.
The Korean Journal of History (Yoksahak Yongu), 100, 267-297.
https://doi.org/10.37924/JSSW.100.9
```

서비스의 `/health`와 `/punctuate` 응답에는 `PUNCT_ENGINE=sikurroberta`일 때 위 출처
메타데이터가 `attribution` 필드로 포함된다. 본체도 외부 표점 결과에 이 필드를 전달하며,
구버전 서비스처럼 필드가 비어 있는 경우에도 동일한 출처 메타데이터를 보강한다.

## 모델 가중치 받기

[yachagye 레포 README](https://github.com/yachagye/korean-classical-chinese-punctuation)의
Google Drive 링크에서 `.ckpt`를 받는다. 두 버전 중 v2.5 (SikuRoBERTa, F1 0.91)를 권장.
받은 파일은 `Downloads/classical-text-browser-models/punctuation/` 아래에 풀어두고,
`punctuation-service/.env`의 `PUNCT_MODEL_HOST_PATH`가 실제 `.ckpt` 파일을 가리키게 한다.

## 트러블슈팅

**`/health`가 `ready: false`로 응답**
- `docker compose logs punctuation` 으로 컨테이너 로그 확인
- 가중치 파일 경로(`PUNCT_MODEL_HOST_PATH`)가 실제 호스트에 존재하는지 확인
- 컨테이너 내부 마운트 확인: `docker compose exec punctuation ls -l /models/`

**첫 호출이 매우 느림 (수십 초~분)**
- base BERT가 HuggingFace에서 다운로드되는 중. 이후 호출은 빠름.
- 컨테이너 재시작 시 캐시 유지를 위해 HuggingFace 캐시 볼륨이 마운트되어 있는지 확인
  (`docker volume ls`에서 `punct_huggingface_cache` 또는 `HF_CACHE_VOLUME`에 적은 이름).

**`hyper_parameters` 또는 `state_dict` 키 mismatch 에러**
- yachagye 모델 구조와 본 어댑터의 가정이 어긋났을 가능성. 컨테이너 안에서 다음으로 진단:
  ```bash
  docker compose exec punctuation python -c \
    "import torch; ck=torch.load('/models/checkpoint.ckpt', map_location='cpu', weights_only=False); \
     print(list(ck.get('hyper_parameters',{}).keys())); \
     print(sorted({k.split('.')[0] for k in ck.get('state_dict',{}).keys()}))"
  ```
  결과를 알려주면 어댑터 보정 가능.

**CUDA가 잡히지 않음 (`cuda: False`)**
- compose의 `deploy.resources.reservations.devices` 블록이 적용됐는지 확인.
- Docker Desktop의 NVIDIA 컨테이너 툴킷이 활성화되어 있는지 확인.
- 호스트에 NVIDIA 드라이버가 설치되어 있는지 확인.

**본체 UI에 옵션이 안 보임**
- 브라우저 캐시. 강제 새로고침(Ctrl+F5).
- 기본 URL이 아닌 곳에 서비스를 띄웠다면 본체 재시작 시 `EXTERNAL_PUNCT_URL`이
  환경에 있는지 확인.

## 검증 상태 (2026-05-08 시점)

- ✅ Docker 빌드 성공 — **공식 베이스**(`pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime`)에서
  실측 확인(2026-07-26): torch 2.6.0+cu124 · CUDA 사용가능 True · RTX 3070 Ti 인식 ·
  transformers 4.57.6 · 컨테이너 기동 후 `/health` 200, `/punctuate` 200
- ✅ 컨테이너 안에서 `punctuation_service.sikurroberta` 모듈 import 정상
- ✅ Mock 엔진으로 본체 ↔ 서비스 HTTP 통합 동작 확인
- ✅ v2.5 가중치 다운로드 및 `PUNCT_MODEL_HOST_PATH` 방식 확인
- ⏳ 실제 추론 품질은 로컬 e2e에서 최종 확인
- ✅ 본체 정식 릴리스 `v1.1.4`에 포함

## 디렉토리 구조

```
punctuation-service/
├── pyproject.toml          ← 독립 uv 프로젝트
├── uv.lock
├── Dockerfile              ← ARG BASE_IMAGE (기본: PyTorch 공식 CUDA 이미지)
├── docker-compose.yml      ← GPU + HF 캐시 공유
├── .dockerignore
├── .gitignore
├── README.md               ← 본 문서
└── punctuation_service/
    ├── __init__.py
    ├── __main__.py         ← `python -m punctuation_service`
    ├── api.py              ← FastAPI app
    ├── engine.py           ← Mock + SikuRoBERTa 엔진
    └── sikurroberta.py     ← Lightning 의존성 없는 추론 어댑터
```
