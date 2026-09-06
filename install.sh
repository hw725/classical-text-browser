#!/usr/bin/env bash
# 고전서지 통합 브라우저 — 설치 스크립트 (macOS / Linux)

set -e

echo ""
echo "============================================"
echo "  고전서지 통합 브라우저 — 설치"
echo "============================================"
echo ""

# ── 1. Python 확인/설치 ────────────────────
echo "[1/5] Python 확인 중..."
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
echo "[2/5] Git 확인 중..."
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
echo "[3/5] uv (패키지 관리자) 확인 중..."
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

# ── 4. 본체와 글자 인식 엔진 ─────────────────
echo ""
echo "[4/5] 본체 설치"
echo "  글자 인식(OCR) 엔진을 함께 깔 수 있습니다."
echo ""
echo "    1) 본체만              1~2분. 한글 논문·글자가 든 PDF는 이것만으로 다 됩니다."
echo "    2) + 고서 엔진         3~5분, +170MB. 한문 고서(古典籍) 스캔을 읽습니다."
echo "    3) + 고서·일본어 엔진  5분+, +340MB. 근현대 일본어 자료까지."
echo ""
echo "  나중에 바꿔도 됩니다 — 앱 안 설정 ▸ 처음 설정 ▸ 글자 인식의 「설치」 단추."
echo ""
read -r -p "  고르세요 [1/2/3] (그냥 Enter = 1): " pick
extras=()
case "${pick:-1}" in
    2) extras=(--extra classical) ;;
    3) extras=(--extra classical --extra japanese) ;;
    1) ;;
    *) echo "  «$pick»은 없는 번호라 본체만 깝니다." ;;
esac
echo ""
echo "  받는 중… (진행 표시가 멈춰 보여도 기다리세요)"
uv sync "${extras[@]}"

# ── 5. 글자 인식 모델 미리 받기 ──────────────
echo ""
echo "[5/5] 글자 인식 모델 미리 받기 (처음 한 번, 약 240MB, 인터넷 필요)"
uv run python scripts/warmup_paddle.py korean ch || echo "  모델을 지금 받지 못했습니다. 첫 OCR 때 다시 받습니다."

# ── 5-1. Ollama 기본 비전 모델 ────────────────
if command -v ollama >/dev/null 2>&1; then
    echo ""
    # 기본은 클라우드 모델 — 내려받는 파일이 없고(몇 초) ollama.com 로그인이 있어야 돈다(D-114).
    echo "[5-1] Ollama 기본 비전 모델 확인 (gemma4:cloud)"
    if ollama list 2>/dev/null | grep -q "gemma4:cloud"; then
        echo "  이미 있습니다."
    elif ollama list >/dev/null 2>&1; then
        echo "  없습니다. 등록합니다 (클라우드 모델 — 내려받는 파일 없음, 몇 초)…"
        ollama pull gemma4:cloud || echo "  지금 등록하지 못했습니다. 앱 설정 ▸ LLM 연결 ▸ Ollama의 「모델 받기」에서 고를 수 있습니다."
        echo "  쓰려면 앱 설정 ▸ LLM 연결 ▸ Ollama의 「로그인」. 로그인 없이 쓰려면 같은 자리 「모델 받기」에서 내 PC용 모델을 고르세요."
    else
        echo "  Ollama가 떠 있지 않아 건너뜁니다."
    fi
fi

# ── 완료 ───────────────────────────────────
echo "============================================"
echo "  설치가 완료되었습니다!"
echo "============================================"
echo ""
echo "  서버 시작:  ./start_server.sh"
echo ""
echo "  처음 켜면 «처음 설정» 안내가 떠서 서고 만들기·글자 인식 엔진·AI 연결을 한 자리에서 끝냅니다."
echo "  API 키는 화면에서 넣습니다 — .env 파일을 편집할 일은 없습니다."
echo ""
