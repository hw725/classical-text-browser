@echo off
setlocal
cd /d "%~dp0"

REM ============================================
REM  Classical Text Browser - installer launcher
REM
REM  KEEP THIS FILE ASCII-ONLY (comments too).
REM  cmd.exe under "chcp 65001" miscounts the
REM  bytes of multibyte characters and starts
REM  parsing in the middle of a line, producing
REM  errors such as:
REM    "'...' is not recognized as an internal
REM     or external command"
REM  All Korean text lives in install.ps1, which
REM  PowerShell reads as UTF-8 correctly.
REM ============================================

where powershell >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Windows PowerShell was not found.
    echo Install manually instead:  uv sync
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
