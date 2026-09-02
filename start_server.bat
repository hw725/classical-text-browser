@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

REM NOTE: keep this file pure ASCII (no Korean, even in comments).
REM With "chcp 65001" active, cmd.exe miscounts its byte position in a batch file
REM that contains multi-byte characters and resumes parsing in the middle of a later
REM line (observed 2026-09-03: "'3...' is not recognized as an internal command").
REM tests/test_doc_drift.py::test_batch_files_are_ascii enforces this.

REM ============================================
REM  Classical Text Browser
REM ============================================

REM -- Check uv --------------------------------
uv --version >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo [ERROR] uv is not installed.
    echo.
    echo   Run install.bat first.
    echo.
    pause
    exit /b 1
)

REM -- GPU auto-detect (D-078) -----------------
REM .venv = CPU baseline (lockfile as-is), .venv-gpu = GPU env (created separately).
REM If an NVIDIA GPU is visible and .venv-gpu exists, call that python directly.
REM Why not "uv run": it re-syncs the env to the lockfile before running and
REM would strip the extra GPU stack. Direct invocation is the only safe way.
set "APP_PY=uv run python"
if exist ".venv-gpu\Scripts\python.exe" (
    call nvidia-smi -L >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        REM Check that the GPU env actually works. A stale .venv-gpu (Python 3.13, broken paddle)
        REM used to be picked anyway and the UI only showed "PaddleOCR unavailable".
        REM Use the GPU env if either torch (TrOCR) or paddle imports.
        ".venv-gpu\Scripts\python.exe" -c "import torch" >nul 2>&1
        set "GPU_HAS_TORCH=!ERRORLEVEL!"
        ".venv-gpu\Scripts\python.exe" -c "import paddle" >nul 2>&1
        set "GPU_HAS_PADDLE=!ERRORLEVEL!"
        if "!GPU_HAS_TORCH!"=="0" (
            set "APP_PY=.venv-gpu\Scripts\python.exe"
            echo [Env] NVIDIA GPU detected - using .venv-gpu
            REM torch and paddle ship different cuDNN DLLs and cannot share a process (D-091).
            REM PaddleOCR therefore runs in a child process using the .venv (CPU) python.
            if exist ".venv\Scripts\python.exe" (
                set "CTB_PADDLE_PYTHON=%CD%\.venv\Scripts\python.exe"
                echo [Env] PaddleOCR runs in .venv ^(CPU worker^) - torch/paddle cuDNN conflict
            )
        ) else if "!GPU_HAS_PADDLE!"=="0" (
            set "APP_PY=.venv-gpu\Scripts\python.exe"
            echo [Env] NVIDIA GPU detected - using .venv-gpu ^(paddle GPU^)
        ) else (
            echo [Env] neither torch nor paddle imports in .venv-gpu - falling back to .venv ^(CPU^)
            echo [Env] run doctor.bat to see why. An unused .venv-gpu can be deleted.
        )
    ) else (
        echo [Env] no GPU detected - using .venv ^(CPU^)
    )
) else (
    echo [Env] using .venv ^(CPU^)
)
for /f "tokens=*" %%v in ('%APP_PY% -c "import sys; print(sys.version.split()[0])" 2^>nul') do echo [Env] Python %%v

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
                echo               Note: the first punctuation request loads the model
                echo               and may take a few minutes. The app shows progress.
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
REM The proxy runs in the background without a window: "start /b" opens no new window,
REM runs behind this console, and its output goes to logs\openai-oauth.log.
REM Why no window: "start /min" is ignored by Windows Terminal (the Windows 11
REM default), so the window stays open and is noisy - observed 2026-07-17.
REM If login is required, the user opens the log file to see the instructions.
REM Side effect: closing this window also ends the proxy - no leftover process.
REM Caution: never put REM inside a parenthesized block - a closing paren in the
REM comment ends the block early and the whole script dies with a parse error.
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
            echo [OpenAI OAuth] starting local proxy in the background...
            if not exist "logs" mkdir "logs"
            start "" /b cmd /c "npx.cmd -y openai-oauth >> logs\openai-oauth.log 2>&1"
            timeout /t 4 /nobreak >nul
            call :check_openai_oauth
            if "!OPENAI_OAUTH_READY!"=="1" (
                set OPENAI_OAUTH_BASE_URL=http://127.0.0.1:!OPENAI_OAUTH_PORT!/v1
                echo [OpenAI OAuth] proxy ready at !OPENAI_OAUTH_BASE_URL!
            ) else (
                echo [OpenAI OAuth] proxy is starting in the background - no window.
                echo               Output: logs\openai-oauth.log
                echo               If login is required, that file will contain instructions.
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
REM start /b + hidden PowerShell: the old way (start cmd /c timeout...) opened a
REM 2-second cmd window, so startup looked like 3 windows. Now no extra window.
start /b "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:!PORT!'"

REM -- Run server ------------------------------
if "%LIBRARY_PATH%"=="" (
    !APP_PY! -m app serve --port !PORT!
) else (
    !APP_PY! -m app serve --library "%LIBRARY_PATH%" --port !PORT!
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
