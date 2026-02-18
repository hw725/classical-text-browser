@echo off
setlocal enabledelayedexpansion

REM ============================================
REM  Classical Text Digital Library Platform
REM ============================================

REM -- Settings --------------------------------
REM Change LIBRARY_PATH to your library directory.
set LIBRARY_PATH=examples\monggu_library
set PORT=8000

REM -- Check library ---------------------------
if not exist "%LIBRARY_PATH%\library_manifest.json" (
    echo [ERROR] Library not found: %LIBRARY_PATH%
    echo.
    echo Fix: change LIBRARY_PATH in this file, or create a library first:
    echo   uv run python -m cli init-library path
    echo.
    pause
    exit /b 1
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
echo  Classical Text Digital Library Platform
echo ============================================
echo.
echo [Library] %LIBRARY_PATH%
echo [Server]  http://127.0.0.1:%PORT%
echo.
echo Press Ctrl+C to stop the server.
echo.

REM -- Open browser after 2 seconds -----------
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:!PORT!"

REM -- Run server ------------------------------
uv run python -m app serve --library "%LIBRARY_PATH%" --port !PORT!

echo.
echo Server stopped.
pause
