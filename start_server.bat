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

REM -- Optional punctuation service ----------------
REM If punctuation-service\.env exists or PUNCT_MODEL_HOST_PATH is set, start the
REM Dockerized SikuRoBERTa punctuation service in the background. The main app
REM defaults to http://127.0.0.1:8765, so no EXTERNAL_PUNCT_URL is needed.
REM Set PUNCT_AUTO_START=0 to skip this.
set PUNCT_SERVICE_CONFIGURED=0
if exist "punctuation-service\.env" set PUNCT_SERVICE_CONFIGURED=1
if not "%PUNCT_MODEL_HOST_PATH%"=="" set PUNCT_SERVICE_CONFIGURED=1

if /I "%PUNCT_AUTO_START%"=="0" (
    echo [Punctuation] auto-start disabled by PUNCT_AUTO_START=0
) else if "%PUNCT_SERVICE_CONFIGURED%"=="1" (
    docker --version >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        echo [Punctuation] Docker not found. Start punctuation-service manually if needed.
    ) else (
        docker compose version >nul 2>&1
        if !ERRORLEVEL! neq 0 (
            echo [Punctuation] Docker Compose not available. Start punctuation-service manually if needed.
        ) else (
            echo [Punctuation] starting http://127.0.0.1:8765 ...
            pushd punctuation-service >nul
            docker compose up -d
            if !ERRORLEVEL! neq 0 (
                echo [Punctuation] failed to start. The main server will continue.
            ) else (
                echo [Punctuation] service ready or starting in background.
            )
            popd >nul
        )
    )
) else (
    echo [Punctuation] no model path configured. Skipping external punctuation service.
    echo              To enable: create punctuation-service\.env with PUNCT_MODEL_HOST_PATH=...
)

REM -- Optional OpenAI OAuth proxy -----------------
REM The UI exposes "OpenAI (OAuth)", so start the local OpenAI-compatible proxy
REM when npx.cmd is available. Set OPENAI_OAUTH_AUTO_START=0 to skip this.
if /I "%OPENAI_OAUTH_AUTO_START%"=="0" (
    echo [OpenAI OAuth] auto-start disabled by OPENAI_OAUTH_AUTO_START=0
) else (
    where npx.cmd >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        echo [OpenAI OAuth] npx.cmd not found. Install Node.js or start openai-oauth manually.
    ) else (
        call :check_openai_oauth
        if "!OPENAI_OAUTH_READY!"=="1" (
            set OPENAI_OAUTH_BASE_URL=http://127.0.0.1:!OPENAI_OAUTH_PORT!/v1
            echo [OpenAI OAuth] proxy ready at !OPENAI_OAUTH_BASE_URL!
        ) else (
            echo [OpenAI OAuth] starting local proxy...
            start "OpenAI OAuth Proxy" cmd /k "npx.cmd -y openai-oauth"
            timeout /t 4 /nobreak >nul
            call :check_openai_oauth
            if "!OPENAI_OAUTH_READY!"=="1" (
                set OPENAI_OAUTH_BASE_URL=http://127.0.0.1:!OPENAI_OAUTH_PORT!/v1
                echo [OpenAI OAuth] proxy ready at !OPENAI_OAUTH_BASE_URL!
            ) else (
                echo [OpenAI OAuth] proxy window opened. Complete login there if prompted.
                echo               The main server will continue and will detect the proxy when it is ready.
            )
        )
    )
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
set APP_EXIT_CODE=!ERRORLEVEL!

echo.
echo Server stopped.
pause
exit /b !APP_EXIT_CODE!

:check_openai_oauth
set OPENAI_OAUTH_READY=0
set OPENAI_OAUTH_PORT=
for /L %%P in (10531,1,10540) do (
    curl.exe --silent --fail --max-time 2 -H "Authorization: Bearer oauth-proxy" "http://127.0.0.1:%%P/v1/models" 2>nul | findstr /I /C:"data" >nul
    if !ERRORLEVEL! equ 0 (
        set OPENAI_OAUTH_READY=1
        set OPENAI_OAUTH_PORT=%%P
        goto :eof
    )
)
goto :eof
