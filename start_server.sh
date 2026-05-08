#!/usr/bin/env bash
# 고전서지 통합 브라우저 — 서버 실행 스크립트

set -e

# ── uv 확인 ──────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
    echo "[오류] uv가 설치되어 있지 않습니다."
    echo ""
    echo "  먼저 ./install.sh 를 실행하세요."
    exit 1
fi

# ── 설정 ──────────────────────────────────────
# 서고 경로: 첫 번째 인자(선택)
# 비워두면 --library 없이 실행되어 GUI에서 서고를 선택/변경할 수 있다.
LIBRARY_PATH="${1:-}"

# 서버 포트: 두 번째 인자 또는 기본값 (사용 중이면 자동으로 다음 포트 시도)
PORT="${2:-8000}"

# ── 서고 확인 ─────────────────────────────────
if [ -n "$LIBRARY_PATH" ] && [ ! -f "$LIBRARY_PATH/library_manifest.json" ]; then
    echo "[오류] 서고를 찾을 수 없습니다: $LIBRARY_PATH"
    echo ""
    echo "사용법: ./start_server.sh [서고 경로] [포트]"
    echo "  예: ./start_server.sh"
    echo "  예: ./start_server.sh examples/monggu_library 8000"
    echo ""
    echo "서고 생성: uv run python -m cli init-library <경로>"
    exit 1
fi

# ── 빈 포트 찾기 ──────────────────────────────
MAX_TRIES=10
TRY=0
while [ $TRY -lt $MAX_TRIES ]; do
    if ! lsof -i ":$PORT" -sTCP:LISTEN >/dev/null 2>&1 && \
       ! ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
        break  # 포트 사용 가능
    fi
    echo "[알림] 포트 $PORT가 이미 사용 중입니다. 다음 포트를 시도합니다..."
    PORT=$((PORT + 1))
    TRY=$((TRY + 1))
done

if [ $TRY -ge $MAX_TRIES ]; then
    echo "[오류] 포트 ${2:-8000}~$PORT 모두 사용 중입니다."
    exit 1
fi

# ── 외부 표점 서비스 자동 시작(선택) ─────────────
# punctuation-service/.env 또는 PUNCT_MODEL_HOST_PATH가 있으면 Docker Compose로
# SikuRoBERTa 표점 서비스를 백그라운드 기동한다. 본체는 기본적으로
# http://127.0.0.1:8765를 사용하므로 EXTERNAL_PUNCT_URL은 필요 없다.
# 건너뛰려면 PUNCT_AUTO_START=0 ./start_server.sh
PUNCT_SERVICE_CONFIGURED=0
if [ -f "punctuation-service/.env" ] || [ -n "${PUNCT_MODEL_HOST_PATH:-}" ]; then
    PUNCT_SERVICE_CONFIGURED=1
fi

if [ "${PUNCT_AUTO_START:-1}" = "0" ]; then
    echo "[표점] PUNCT_AUTO_START=0 으로 자동 시작을 건너뜁니다."
elif [ "$PUNCT_SERVICE_CONFIGURED" = "1" ]; then
    if ! command -v docker >/dev/null 2>&1; then
        echo "[표점] Docker를 찾을 수 없습니다. 필요하면 표점 서비스를 수동으로 시작하세요."
    elif ! docker compose version >/dev/null 2>&1; then
        echo "[표점] Docker Compose를 사용할 수 없습니다. 필요하면 표점 서비스를 수동으로 시작하세요."
    else
        echo "[표점] http://127.0.0.1:8765 서비스를 시작합니다..."
        if (cd punctuation-service && docker compose up -d); then
            echo "[표점] 서비스가 백그라운드에서 시작 중입니다."
        else
            echo "[표점] 서비스 시작에 실패했습니다. 본체 서버는 계속 실행합니다."
        fi
    fi
else
    echo "[표점] 모델 경로가 설정되지 않아 외부 표점 서비스 자동 시작을 건너뜁니다."
    echo "       사용하려면 punctuation-service/.env에 PUNCT_MODEL_HOST_PATH=... 를 설정하세요."
fi

echo "============================================"
echo "  고전서지 통합 브라우저"
echo "============================================"
echo ""
if [ -n "$LIBRARY_PATH" ]; then
    echo "[서고] $LIBRARY_PATH"
else
    echo "[서고] (없음 - 시작 후 GUI에서 선택/변경)"
fi
echo "[서버] http://127.0.0.1:$PORT"
echo ""
echo "종료하려면 Ctrl+C를 누르세요."
echo ""

# ── 브라우저 자동 열기 (2초 후) ────────────────
(
    sleep 2
    if command -v open >/dev/null 2>&1; then
        open "http://127.0.0.1:$PORT"           # macOS
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "http://127.0.0.1:$PORT"       # Linux (GNOME/KDE 등)
    else
        echo "[알림] 브라우저를 열 수 없습니다. 직접 http://127.0.0.1:$PORT 에 접속하세요."
    fi
) &

# ── 서버 실행 ─────────────────────────────────
if [ -n "$LIBRARY_PATH" ]; then
    uv run python -m app serve --library "$LIBRARY_PATH" --port "$PORT"
else
    uv run python -m app serve --port "$PORT"
fi
