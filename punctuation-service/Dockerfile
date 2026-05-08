# 베이스: 사용자의 NLP 작업 이미지를 그대로 재사용.
# torch 2.6.0+cu124, transformers 4.57.3, CUDA 런타임이 이미 갖춰져 있다.
# 본 서비스는 그 위에 FastAPI 계층만 얹는다.
FROM csp-csp:latest

# 추가 의존성: 서비스 계층(fastapi/uvicorn/pydantic)만.
# torch·transformers·numpy는 부모 이미지에서 제공.
RUN pip install --no-cache-dir \
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
