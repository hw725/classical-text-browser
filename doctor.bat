@echo off
chcp 65001 >nul 2>&1
REM Environment doctor: inspects .venv and .venv-gpu, explains why PaddleOCR etc.
REM are unavailable and recommends what to delete or keep. Deletes nothing.
REM Keep this file pure ASCII (see start_server.bat header).
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" scripts\doctor.py %*
) else if exist ".venv-gpu\Scripts\python.exe" (
    ".venv-gpu\Scripts\python.exe" scripts\doctor.py %*
) else (
    python scripts\doctor.py %*
)
echo.
pause
