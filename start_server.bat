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

REM -- GPU auto-detect (D-078) -----------------
REM .venv = CPU 정본(락파일 그대로), .venv-gpu = GPU 환경(별도 생성).
REM NVIDIA GPU가 보이고 .venv-gpu가 있으면 그 환경의 python을 직접 쓴다.
REM 왜 uv run을 안 쓰나: uv run은 실행 전 락 기준으로 환경을 되돌려서
REM GPU 환경의 추가 스택을 지운다 - 직접 호출이 유일하게 안전하다.
set "APP_PY=uv run python"
if exist ".venv-gpu\Scripts\python.exe" (
    call nvidia-smi -L >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        REM GPU 환경이 실제로 쓸 수 있는지 확인한다. 옛 .venv-gpu(파이썬 3.13, 깨진 paddle)가
        REM 남아 있으면 예전에는 그대로 골라서 화면에 «PaddleOCR 사용 불가»만 떴다.
        REM torch(TrOCR)나 paddle 중 하나라도 뜨면 GPU 환경을 쓴다.
        ".venv-gpu\Scripts\python.exe" -c "import torch" >nul 2>&1
        set "GPU_HAS_TORCH=!ERRORLEVEL!"
        ".venv-gpu\Scripts\python.exe" -c "import paddle" >nul 2>&1
        set "GPU_HAS_PADDLE=!ERRORLEVEL!"
        if "!GPU_HAS_TORCH!"=="0" (
            set "APP_PY=.venv-gpu\Scripts\python.exe"
            echo [Env] NVIDIA GPU detected - using .venv-gpu
            REM torch와 paddle은 cuDNN DLL이 달라 한 프로세스에 못 산다(D-091).
            REM PaddleOCR은 .venv^(CPU^)의 파이썬을 자식 프로세스로 띄워 돌린다.
            if exist ".venv\Scripts\python.exe" (
                set "CTB_PADDLE_PYTHON=%CD%\.venv\Scripts\python.exe"
                echo [Env] PaddleOCR runs in .venv ^(CPU worker^) - torch/paddle cuDNN conflict
            )
        ) else if "!GPU_HAS_PADDLE!"=="0" (
            set "APP_PY=.venv-gpu\Scripts\python.exe"
            echo [Env] NVIDIA GPU detected - using .venv-gpu ^(paddle GPU^)
        ) else (
            echo [Env] .venv-gpu 에서 torch 도 paddle 도 뜨지 않아 .venv ^(CPU^) 로 뜁니다.
            echo [Env] 원인은 doctor.bat 으로 확인하세요. 안 쓰는 .venv-gpu 는 지워도 됩니다.
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
REM 프록시는 창 없이 백그라운드로 돌린다 - start /b 는 새 창을 만들지 않고
REM 이 콘솔 뒤에서 실행하며, 출력은 logs\openai-oauth.log 로 보낸다.
REM 왜 창을 안 만드는가: start /min 은 Windows 11 기본 터미널인
REM Windows Terminal 에서 무시되어 창이 그대로 떠서 시끄럽다 - 2026-07-17 실측.
REM 로그인 안내가 필요하면 사용자가 로그 파일을 열어 확인한다.
REM 부수 효과: 이 창을 닫으면 프록시도 함께 종료된다 - 잔여 프로세스가 없다.
REM 주의: 괄호 블록 안에는 REM을 넣지 말 것 - 주석 속 닫는 괄호가
REM 블록을 조기 종료시켜 스크립트 전체가 파싱 오류로 죽는다.
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
REM start /b + 숨김 PowerShell: 예전 방식(start cmd /c timeout...)은 2초짜리
REM cmd 창을 하나 더 띄워 시작 시 창이 3개처럼 보였다. 이제 창 없이 연다.
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
