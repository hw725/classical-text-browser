#!/usr/bin/env bash
# 고전서지 통합 브라우저 — 설치 스크립트 (macOS / Linux)

set -e

echo ""
echo "============================================"
echo "  고전서지 통합 브라우저 — 설치"
echo "============================================"
echo ""

# ── 1. Python 확인/설치 ────────────────────
echo "[1/4] Python 확인 중..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "  Python 3이 설치되어 있지 않습니다. 자동 설치합니다..."
    echo ""
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS: Homebrew 사용
        if command -v brew >/dev/null 2>&1; then
            brew install python3
        else
            echo "  Homebrew가 필요합니다. 먼저 Homebrew를 설치합니다..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"
            brew install python3
        fi
    else
        # Linux: apt 또는 dnf
        if command -v apt >/dev/null 2>&1; then
            sudo apt update && sudo apt install -y python3 python3-venv
        elif command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y python3
        else
            echo "[오류] Python 3 자동 설치를 지원하지 않는 환경입니다."
            echo "  직접 설치해주세요: https://www.python.org/downloads/"
            exit 1
        fi
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo "[오류] Python 설치에 실패했습니다."
        exit 1
    fi
fi
echo "  $(python3 --version) 확인됨"

# ── 2. Git 확인/설치 ──────────────────────
echo ""
echo "[2/4] Git 확인 중..."
if ! command -v git >/dev/null 2>&1; then
    echo "  Git이 설치되어 있지 않습니다. 자동 설치합니다..."
    echo ""
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS: Xcode CLT 또는 Homebrew
        if command -v brew >/dev/null 2>&1; then
            brew install git
        else
            xcode-select --install 2>/dev/null || true
            echo "  Xcode Command Line Tools 설치 창이 나타나면 '설치'를 클릭하세요."
            echo "  설치 완료 후 이 스크립트를 다시 실행하세요."
            exit 1
        fi
    else
        if command -v apt >/dev/null 2>&1; then
            sudo apt update && sudo apt install -y git
        elif command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y git
        else
            echo "[오류] Git 자동 설치를 지원하지 않는 환경입니다."
            echo "  직접 설치해주세요: https://git-scm.com/downloads"
            exit 1
        fi
    fi
    if ! command -v git >/dev/null 2>&1; then
        echo "[오류] Git 설치에 실패했습니다."
        exit 1
    fi
fi
echo "  $(git --version) 확인됨"

# ── 3. uv 확인/설치 ───────────────────────
echo ""
echo "[3/4] uv (패키지 관리자) 확인 중..."
if ! command -v uv >/dev/null 2>&1; then
    echo "  uv가 설치되어 있지 않습니다. 자동 설치합니다..."
    echo ""
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        echo "[오류] uv 설치에 실패했습니다."
        echo "  수동 설치: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
fi
echo "  $(uv --version) 확인됨"

# ── 4. 의존성 설치 ─────────────────────────
echo ""
echo "[4/4] 의존성 설치 중... (처음 실행 시 1~2분 소요)"
echo ""
uv sync

# ── .env 파일 안내 ─────────────────────────
echo ""
if [ -f ".env.example" ] && [ ! -f ".env" ]; then
    echo "────────────────────────────────────────────"
    echo "[선택] LLM 기능을 사용하려면 API 키 설정이 필요합니다."
    echo ""
    echo "  1. cp .env.example .env"
    echo "  2. .env 파일을 편집하여 API 키를 입력하세요"
    echo ""
    echo "  지금은 건너뛰어도 됩니다. OCR, 번역 등 LLM 기능만 제한됩니다."
    echo "────────────────────────────────────────────"
    echo ""
fi

# ── 완료 ───────────────────────────────────
echo "============================================"
echo "  설치가 완료되었습니다!"
echo "============================================"
echo ""
echo "  서버 시작:  ./start_server.sh"
echo ""
