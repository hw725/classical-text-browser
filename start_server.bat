@echo off
chcp 65001 >nul 2>&1
title 고전 텍스트 디지털 서고 플랫폼

echo ============================================
echo   고전 텍스트 디지털 서고 플랫폼
echo ============================================
echo.

:: ── 설정 ──────────────────────────────────────
:: 서고 경로를 여기서 변경하세요.
:: 예: set LIBRARY_PATH=C:\Users\junto\my_library
set LIBRARY_PATH=examples\monggu_library

:: 서버 포트 (기본: 8000, 사용 중이면 자동으로 다음 포트 시도)
set PORT=8000

:: ── 서고 확인 ─────────────────────────────────
if not exist "%LIBRARY_PATH%\library_manifest.json" (
    echo [오류] 서고를 찾을 수 없습니다: %LIBRARY_PATH%
    echo.
    echo 해결 방법:
    echo   1. 위의 LIBRARY_PATH 값을 실제 서고 경로로 변경하세요.
    echo   2. 또는 서고를 먼저 생성하세요:
    echo      uv run python -m cli init-library 경로
    echo.
    pause
    exit /b 1
)

:: ── 빈 포트 찾기 ──────────────────────────────
:: 포트가 사용 중이면 자동으로 다음 포트를 시도한다 (최대 10번)
set /a MAX_TRIES=10
set /a TRY=0

:find_port
netstat -an | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [알림] 포트 %PORT%가 이미 사용 중입니다. 다음 포트를 시도합니다...
    set /a PORT+=1
    set /a TRY+=1
    if %TRY% lss %MAX_TRIES% goto find_port
    echo [오류] 포트 8000~%PORT% 모두 사용 중입니다.
    echo   다른 프로그램을 종료하거나, 이 파일의 PORT 값을 변경하세요.
    pause
    exit /b 1
)

echo [서고] %LIBRARY_PATH%
echo [서버] http://127.0.0.1:%PORT%
echo.
echo 브라우저에서 http://127.0.0.1:%PORT% 을 여세요.
echo 종료하려면 이 창에서 Ctrl+C를 누르세요.
echo.

:: ── 서버 실행 ─────────────────────────────────
uv run python -m app serve --library "%LIBRARY_PATH%" --port %PORT%

:: 서버가 종료된 경우
echo.
echo 서버가 종료되었습니다.
pause
