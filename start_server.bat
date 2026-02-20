@echo off
setlocal enabledelayedexpansion

REM ============================================
REM  Classical Text Digital Library Platform
REM ============================================

REM -- Settings --------------------------------
REM Optional first arg: library path (empty = start without --library)
set LIBRARY_PATH=%~1
set PORT=8000

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
echo  Classical Text Digital Library Platform
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
