# 표점 서비스 이미지.
#
# 베이스를 **인자로 받는다** — 이 파일에서 가장 중요한 한 줄이다.
#
# 왜: 예전에는 `FROM csp-csp:latest`로 고정돼 있었다. 그것은 개발자 PC에만 있는
# 개인 NLP 작업 이미지라, **다른 사람이 이 저장소를 받으면 빌드가 실패한다.**
# Windows에서 GPU(CUDA)로 표점을 돌리려면 이 컨테이너가 필요한데, 만들 방법이
# 없었다. 표점을 「선택 기능」으로 두는 것과 「만들 수 없는 기능」으로 두는 것은
# 다르다.
#
# 기본값은 PyTorch 공식 CUDA 이미지다 — 누구나 그대로 빌드할 수 있다.
# 이미 torch+CUDA가 든 이미지를 갖고 있다면 그것을 베이스로 재사용하면
# 내려받기 수 GB를 아낄 수 있고, 그때만 BASE_IMAGE를 넘긴다.
#
#   # 누구나 (기본) — 공식 이미지에서 만든다
#   docker compose up -d --build
#
#   # 이미 torch+CUDA 이미지가 있다면 그것을 베이스로
#   BASE_IMAGE=csp-csp:latest docker compose up -d --build
#
# CUDA 12.4 / cuDNN 9 런타임 — 본체 pyproject의 pytorch-cu124 인덱스와 맞췄다.
ARG BASE_IMAGE=pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime
FROM ${BASE_IMAGE}

# 의존성.
#
# **torch는 건드리지 않는다.** 여기서 pip install torch를 하면 베이스의 CUDA
# 빌드를 CPU 빌드로 덮어써 GPU가 조용히 죽는다 — 오류 없이 느려질 뿐이라
# 알아채기 어렵다.
#
# transformers는 공식 PyTorch 이미지에 없으므로 여기서 넣는다. 이미 들어 있는
# 베이스(csp-csp 등)에서는 조건을 만족해 그대로 통과한다.
#
# **상한 <5를 두는 이유**: 이 서비스가 실제로 돌아가는 것을 확인한 조합은
# transformers 4.57.3뿐이다(개발자 이미지). 상한 없이 두었더니 5.14.1이 들어왔다.
# `AutoModel`·`AutoTokenizer` import는 5.x에서도 되지만, 가중치(.ckpt)를 실제로
# 불러 추론한 적은 없다. 이 저장소의 경험상 NLP 스택의 메이저 상승은 예외가
# 아니라 **조용한 오작동**으로 나타난다. 확인한 뒤에 올린다.
RUN pip install --no-cache-dir \
        "transformers>=4.30,<5" \
        "fastapi>=0.110" \
        "uvicorn[standard]>=0.27" \
        "pydantic>=2.5"

# 서비스 코드 복사. 모델 가중치(.ckpt)는 런타임 마운트로 주입한다.
WORKDIR /app
COPY punctuation_service/ /app/punctuation_service/

EXPOSE 8765

# 안전 기본값: 가중치 없이 실수로 띄워도 mock으로 작동.
# 실제 추론은 docker compose / docker run 에서 PUNCT_ENGINE=sikurroberta로 덮어쓴다.
ENV PUNCT_ENGINE=mock \
    PUNCT_HOST=0.0.0.0 \
    PUNCT_PORT=8765 \
    PUNCT_DEVICE=auto \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "punctuation_service"]
