#!/usr/bin/env bash
# 고전 텍스트 디지털 서고 플랫폼 — 서버 실행 스크립트

set -e

# ── 설정 ──────────────────────────────────────
# 서고 경로: 첫 번째 인자 또는 기본값
LIBRARY_PATH="${1:-examples/monggu_library}"

# 서버 포트: 두 번째 인자 또는 기본값 (사용 중이면 자동으로 다음 포트 시도)
PORT="${2:-8000}"

# ── 서고 확인 ─────────────────────────────────
if [ ! -f "$LIBRARY_PATH/library_manifest.json" ]; then
    echo "[오류] 서고를 찾을 수 없습니다: $LIBRARY_PATH"
    echo ""
    echo "사용법: ./start_server.sh <서고 경로> [포트]"
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

echo "============================================"
echo "  고전 텍스트 디지털 서고 플랫폼"
echo "============================================"
echo ""
echo "[서고] $LIBRARY_PATH"
echo "[서버] http://127.0.0.1:$PORT"
echo ""
echo "브라우저에서 http://127.0.0.1:$PORT 을 여세요."
echo "종료하려면 Ctrl+C를 누르세요."
echo ""

# ── 서버 실행 ─────────────────────────────────
uv run python -m app serve --library "$LIBRARY_PATH" --port "$PORT"
