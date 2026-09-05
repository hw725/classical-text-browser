# 고전서지 통합 브라우저 — 설치
#
# 왜 .bat이 아니라 .ps1인가:
#   cmd.exe는 `chcp 65001`을 걸어도 다중바이트 글자의 길이를 잘못 세어, 한글이 든 줄의
#   중간부터 명령으로 읽는다. 그래서 「'모장으로'은(는) 내부 또는 외부 명령이 아닙니다」
#   같은 오류가 났다. PowerShell은 UTF-8을 제대로 읽으므로 사람에게 보이는 말은 전부
#   이 파일에 둔다. install.bat은 이 파일을 부르기만 하는 ASCII 껍데기다.
#
# 이 파일은 반드시 **UTF-8 with BOM**으로 저장한다. BOM이 없으면 Windows PowerShell 5.1이
# 시스템 ANSI 코드페이지로 읽어 한글이 깨진다.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Say([string]$text, [string]$color = "Gray") {
    Write-Host $text -ForegroundColor $color
}

function Fail([string]$text, [string]$how) {
    Write-Host ""
    Say "[막힘] $text" "Red"
    if ($how) { Say "  → $how" "Yellow" }
    Write-Host ""
    exit 1
}

# winget·설치 스크립트가 PATH를 바꾼 뒤에는 이 프로세스의 PATH도 다시 읽어야 한다.
# 그러지 않으면 방금 깐 것을 「없다」고 판단해 사용자에게 창을 닫으라고 하게 된다.
function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $extra = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;C:\Program Files\Git\cmd"
    $env:PATH = "$extra;$user;$machine"
}

function Have([string]$exe) {
    $null = Get-Command $exe -ErrorAction SilentlyContinue
    return $?
}

Write-Host ""
Say "============================================" "Cyan"
Say "  고전서지 통합 브라우저 — 설치" "Cyan"
Say "============================================" "Cyan"
Write-Host ""
Say "  필요한 것을 확인하고, 없으면 받아서 깝니다."
Say "  처음이면 5~10분쯤 걸립니다. 창을 닫지 마세요."
Write-Host ""

# ── 1. Python ────────────────────────────────────────────────
# 앱은 .python-version(3.12)에 맞는 파이썬을 uv가 알아서 받아 .venv에 붙인다. 시스템에
# 파이썬이 없어도 되고, 3.13이 깔려 있어도 uv는 3.12를 따로 받아 쓴다. 그래서 여기서는
# 있으면 알려 주기만 하고, 없어도 막지 않는다 — winget이 안 되는 기기에서 설치가 멈추지 않게.
Say "[1/4] Python 확인" "White"
if (Have "python") {
    $pyVer = (python --version 2>&1) -join " "
    Say "  $pyVer (있음 — 앱은 별도로 3.12를 씁니다)" "Green"
} else {
    Say "  시스템에 Python이 없습니다. 괜찮습니다 — 4단계에서 uv가 3.12를 받아 앱 전용으로 깝니다." "Yellow"
}

# ── 2. Git ───────────────────────────────────────────────────
Write-Host ""
Say "[2/4] Git 확인" "White"
if (-not (Have "git")) {
    Say "  없습니다. 자동으로 받습니다..."
    winget install --id Git.Git -e --source winget `
        --accept-package-agreements --accept-source-agreements
    Refresh-Path
    if (-not (Have "git")) {
        Fail "Git을 깔았지만 이 창이 아직 못 찾습니다." `
             "이 창을 닫고 install.bat을 한 번 더 실행하세요."
    }
}
Say "  $((git --version) -join ' ')" "Green"

# ── 3. uv ────────────────────────────────────────────────────
Write-Host ""
Say "[3/4] uv (꾸러미 관리자) 확인" "White"
if (-not (Have "uv")) {
    Say "  없습니다. 자동으로 받습니다..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    Refresh-Path
    if (-not (Have "uv")) {
        Fail "uv를 깔았지만 이 창이 아직 못 찾습니다." `
             "이 창을 닫고 install.bat을 한 번 더 실행하세요."
    }
}
Say "  $((uv --version) -join ' ')" "Green"

# ── 4. 본체와 글자 인식 엔진 ─────────────────────────────────
Write-Host ""
Say "[4/4] 본체 설치" "White"
Say "  글자 인식(OCR) 엔진을 함께 깔 수 있습니다."
Write-Host ""
Say "    1) 본체만              1~2분, 약 830MB. 한글 논문·글자가 든 PDF는 이것만으로 다 됩니다."
Say "    2) + 고서 엔진         3~5분, +170MB. 한문 고서(古典籍) 스캔을 읽습니다."
Say "    3) + 고서·일본어 엔진  5분+, +340MB. 근현대 일본어 자료까지."
Write-Host ""
Say "  나중에 바꿔도 됩니다 — 앱 안 설정 ▸ 처음 설정 ▸ 글자 인식의 「설치」 단추."
Say "  GPU판(4.5GB)은 별도 환경에 깝니다 — 사용자 가이드 7-A.6-2." "DarkGray"
Write-Host ""
$pick = Read-Host "  고르세요 [1/2/3] (그냥 Enter = 1)"

# extras 이름은 pyproject.toml의 [project.optional-dependencies]와 같아야 한다.
# 없는 이름을 적으면 uv가 «unknown extra»로 서고, 처음 까는 사람은 왜인지 모른다.
$extras = @()
if ($pick -eq "2") { $extras = @("--extra", "classical") }
elseif ($pick -eq "3") { $extras = @("--extra", "classical", "--extra", "japanese") }

Write-Host ""
Say "  받는 중… (진행 표시가 멈춰 보여도 기다리세요)"
Write-Host ""
uv sync @extras
if ($LASTEXITCODE -ne 0) {
    Fail "설치에 실패했습니다." "위에 찍힌 오류를 그대로 알려 주시면 됩니다."
}

# ── 마무리 ───────────────────────────────────────────────────
Write-Host ""
Say "============================================" "Green"
Say "  설치가 끝났습니다" "Green"
Say "============================================" "Green"
Write-Host ""
Say "  다음: start_server.bat 을 두 번 누르세요." "White"
Write-Host ""
Say "  처음 켜면 «처음 설정» 안내가 떠서 이 셋을 한 자리에서 끝냅니다:"
Say "    · 서고(작업 폴더) 만들기"
Say "    · 글자 인식 엔진 상태 보기"
Say "    · AI 연결 — API 키를 화면에서 넣습니다"
Write-Host ""
Say "  .env 파일을 메모장으로 열 일은 없습니다." "DarkGray"
Write-Host ""
