@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

REM ============================================
REM  고전서지 통합 브라우저 — 설치
REM ============================================
echo.
echo ============================================
echo   고전서지 통합 브라우저 — 설치
echo ============================================
echo.

REM ── 1. Python 확인/설치 ────────────────────
echo [1/4] Python 확인 중...
python --version >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo   Python이 설치되어 있지 않습니다. 자동 설치합니다...
    echo.
    winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
    if !ERRORLEVEL! neq 0 (
        echo.
        echo [오류] Python 자동 설치에 실패했습니다.
        echo   직접 설치해주세요: https://www.python.org/downloads/
        echo   설치할 때 "Add Python to PATH" 체크박스를 반드시 선택하세요.
        echo.
        pause
        exit /b 1
    )
    echo.
    echo   Python 설치 완료. PATH를 갱신합니다...
    REM winget 설치 후 PATH 갱신
    for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "PATH=%%b;%PATH%"
    python --version >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        echo.
        echo [알림] Python이 설치되었지만 PATH에 반영되지 않았습니다.
        echo   이 창을 닫고 새 명령 프롬프트에서 install.bat을 다시 실행하세요.
        echo.
        pause
        exit /b 1
    )
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   %%v 확인됨

REM ── 2. Git 확인/설치 ──────────────────────
echo.
echo [2/4] Git 확인 중...
git --version >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo   Git이 설치되어 있지 않습니다. 자동 설치합니다...
    echo.
    winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
    if !ERRORLEVEL! neq 0 (
        echo.
        echo [오류] Git 자동 설치에 실패했습니다.
        echo   직접 설치해주세요: https://git-scm.com/download/win
        echo.
        pause
        exit /b 1
    )
    echo.
    echo   Git 설치 완료. PATH를 갱신합니다...
    for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "PATH=%%b;%PATH%"
    REM Git은 시스템 PATH에 설치될 수 있으므로 추가 확인
    set "PATH=C:\Program Files\Git\cmd;%PATH%"
    git --version >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        echo.
        echo [알림] Git이 설치되었지만 PATH에 반영되지 않았습니다.
        echo   이 창을 닫고 새 명령 프롬프트에서 install.bat을 다시 실행하세요.
        echo.
        pause
        exit /b 1
    )
)
for /f "tokens=*" %%v in ('git --version 2^>^&1') do echo   %%v 확인됨

REM ── 3. uv 확인/설치 ───────────────────────
echo.
echo [3/4] uv (패키지 관리자) 확인 중...
uv --version >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo   uv가 설치되어 있지 않습니다. 자동 설치합니다...
    echo.
    powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if !ERRORLEVEL! neq 0 (
        echo.
        echo [오류] uv 설치에 실패했습니다.
        echo   수동 설치: https://docs.astral.sh/uv/getting-started/installation/
        echo.
        pause
        exit /b 1
    )
    echo.
    echo   uv 설치 완료. PATH를 갱신합니다...
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
    uv --version >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        echo.
        echo [알림] uv가 설치되었지만 PATH에 반영되지 않았습니다.
        echo   이 창을 닫고 새 명령 프롬프트에서 install.bat을 다시 실행하세요.
        echo.
        pause
        exit /b 1
    )
)
for /f "tokens=*" %%v in ('uv --version 2^>^&1') do echo   %%v 확인됨

REM ── 4. 의존성 설치 ─────────────────────────
echo.
echo [4/4] 의존성 설치 중... (처음 실행 시 1~2분 소요)
echo.
uv sync
if !ERRORLEVEL! neq 0 (
    echo.
    echo [오류] 의존성 설치에 실패했습니다.
    echo   위 에러 메시지를 확인하세요.
    echo.
    pause
    exit /b 1
)

REM ── .env 파일 안내 ─────────────────────────
echo.
if exist ".env.example" (
    if not exist ".env" (
        echo ────────────────────────────────────────────
        echo [선택] LLM 기능을 사용하려면 API 키 설정이 필요합니다.
        echo.
        echo   1. .env.example 파일을 .env로 복사하세요
        echo   2. .env 파일을 메모장으로 열어서 API 키를 입력하세요
        echo.
        echo   지금은 건너뛰어도 됩니다. OCR, 번역 등 LLM 기능만 제한됩니다.
        echo ────────────────────────────────────────────
        echo.
    )
)

REM ── 완료 ───────────────────────────────────
echo ============================================
echo   설치가 완료되었습니다!
echo ============================================
echo.
echo   서버 시작:  start_server.bat 을 더블클릭하세요.
echo.
pause
