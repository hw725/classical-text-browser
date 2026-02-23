@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

REM ============================================
REM  Classical Text Browser
REM ============================================

REM -- Check uv --------------------------------
uv --version >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo [오류] uv가 설치되어 있지 않습니다.
    echo.
    echo   먼저 install.bat 을 실행하세요.
    echo.
    pause
    exit /b 1
)

REM -- Settings --------------------------------
REM First arg: library path (optional, empty = choose in GUI)
REM Second arg: port (optional, default 8000)
set LIBRARY_PATH=%~1
if "%~2"=="" (set PORT=8000) else (set PORT=%~2)

REM -- Check library ---------------------------
if not "%LIBRARY_PATH%"=="" (
    if not exist "%LIBRARY_PATH%\library_manifest.json" (
        echo [ERROR] Library not found: %LIBRARY_PATH%
        echo.
        echo Usage:
        echo   start_server.bat
        echo   start_server.bat examples\monggu_library
        echo.
        pause
        exit /b 1
    )
)

REM -- Find available port ---------------------
set /a MAX_TRIES=10
set /a TRY=0

:find_port
netstat -an 2>nul | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if !ERRORLEVEL! equ 0 (
    echo [INFO] Port %PORT% in use, trying next...
    set /a PORT+=1
    set /a TRY+=1
    if !TRY! lss %MAX_TRIES% goto find_port
    echo [ERROR] Ports 8000~%PORT% all in use.
    pause
    exit /b 1
)

echo ============================================
echo  Classical Text Browser
echo ============================================
echo.
if "%LIBRARY_PATH%"=="" (
    echo [Library] none - choose/change in GUI after startup
) else (
    echo [Library] %LIBRARY_PATH%
)
echo [Server]  http://127.0.0.1:%PORT%
echo.
echo Press Ctrl+C to stop the server.
echo.

REM -- Open browser after 2 seconds -----------
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:!PORT!"

REM -- Run server ------------------------------
if "%LIBRARY_PATH%"=="" (
    uv run python -m app serve --port !PORT!
) else (
    uv run python -m app serve --library "%LIBRARY_PATH%" --port !PORT!
)

echo.
echo Server stopped.
pause
