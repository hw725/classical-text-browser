@echo off
chcp 65001 >nul 2>&1
REM 환경 진단: .venv / .venv-gpu 를 각각 조사해 PaddleOCR 등이 왜 안 되는지와
REM 무엇을 지우고 남길지 알려 준다. 파일은 지우지 않는다.
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
