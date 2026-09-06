# CTB-Setup.exe 빌드 — installer/ctb_setup.py를 PyInstaller로 한 파일 exe로.
#
# 쓰는 법:  powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1
# 결과:     dist/CTB-Setup.exe  (약 10MB, 표준 라이브러리 + tkinter만)
# 왜 uvx인가: 앱의 .venv에 pyinstaller를 넣지 않는다 — 배포 도구는 앱 의존이 아니다.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
uvx --from pyinstaller --python 3.12 pyinstaller --noconfirm --clean --onefile --windowed `
    --name "CTB-Setup" --distpath dist --workpath build/installer --specpath build/installer `
    installer/ctb_setup.py
if ($LASTEXITCODE -ne 0) { throw "pyinstaller 실패 ($LASTEXITCODE)" }
Get-Item dist/CTB-Setup.exe | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
