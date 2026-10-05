# 고전서지 통합 브라우저 — 설치 5-1단계: Ollama 기본 비전 모델 확인·등록
#
# install.ps1이 부른다. 따로 떼어 둔 까닭은 이 단계만 시험할 수 있게 하려는 것이다
# (tests/test_install_ollama_probe.py).
#
# 왜 `ollama list`를 부르지 않는가 (2026-10-06 설치 검증):
#   Ollama가 깔려 있으나 꺼져 있으면 `ollama list`가 Ollama 앱(`ollama app.exe --hide`)을 스스로
#   띄운다. 그 앱이 우리 출력 파이프를 물려받아 닫지 않으므로 `(& ollama list | Out-String)`은
#   EOF를 영원히 기다렸고, install.ps1과 CTB-Setup이 28분 동안 멈춰 있다가 강제 종료됐다.
#   그래서 모델 목록은 HTTP API(/api/tags, 3초 제한)로 읽고, 꺼져 있으면 «나중에 켜면 된다»로 넘어간다.
#   `ollama pull`처럼 명령을 꼭 불러야 하는 자리는 시간 제한이 있는 별도 프로세스로, 핸들을 물려주지
#   않고 띄운다(Invoke-OllamaTimed) — 손자 프로세스가 남아도 아무것도 기다리지 않는다.
#
# 이 파일은 반드시 **UTF-8 with BOM**으로 저장한다(install.ps1과 같은 이유).
#
# 매개변수:
#   -ListOnly          모델 목록만 읽어 찍고 끝낸다(등록하지 않는다 — 검증용)
#   CTB_OLLAMA_PULL_TIMEOUT  등록 한 번의 제한 시간(초, 기본 180)

param([switch]$ListOnly)

$ErrorActionPreference = "Stop"

function Say([string]$text, [string]$color = "Gray") {
    Write-Host $text -ForegroundColor $color
}

# OLLAMA_HOST(「127.0.0.1:11434」·「http://host:port」·「0.0.0.0」 꼴)를 API 주소로 바꾼다.
# Ollama 명령줄과 같은 셈법 — 스킴이 없으면 http, 포트가 없으면 11434, 0.0.0.0은 내 PC.
function Get-OllamaBase {
    $h = "$env:OLLAMA_HOST".Trim()
    if (-not $h) { return "http://127.0.0.1:11434" }
    if ($h -notmatch '^[a-zA-Z][a-zA-Z0-9+.-]*://') { $h = "http://$h" }
    $h = $h.TrimEnd("/")
    try { $u = [Uri]$h } catch { return "http://127.0.0.1:11434" }
    $hostName = $u.Host
    if (-not $hostName -or $hostName -eq "0.0.0.0") { $hostName = "127.0.0.1" }
    if ($hostName -eq "::" -or $hostName -eq "[::]") { $hostName = "[::1]" }
    $port = $u.Port
    if ($h -notmatch ':\d+$') { $port = 11434 }
    return "$($u.Scheme)://$($hostName):$port"
}

# 모델 이름 목록. 닿지 않으면 $null(빈 목록과 다르다 — 빈 목록은 «켜져 있지만 모델이 없다»).
function Get-OllamaModels([string]$base) {
    try {
        $r = Invoke-RestMethod -Uri "$base/api/tags" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
    } catch {
        return $null
    }
    $names = @()
    foreach ($m in @($r.models)) {
        if ($m -and $m.name) { $names += [string]$m.name }
    }
    return , $names
}

# `ollama <인자…>`를 시간 제한을 두고 돌린다. 돌려주는 값: 종료 코드, 시간 초과면 -1, 시작조차 못 하면 -2.
#
# **핸들을 물려주지 않는 시작(UseShellExecute)이어야 한다.** 출력을 파일로 돌리는 Start-Process
# (-Redirect…)도 CreateProcess에 «상속 가능한 핸들 전부 물려주기»를 켜므로, 이 창의 출력 파이프가
# 손자 프로세스(Ollama 앱 등)에까지 넘어가 CTB-Setup이 그 프로세스가 끝날 때까지 기다린다(2026-10-06
# 재현: 남는 자식 30초 → 31초 대기). 셸 실행은 핸들을 물려주지 않는다 — 대신 출력은 보이지 않는다
# (숨긴 창). 시간이 넘으면 프로세스 나무째 끝낸다.
function Invoke-OllamaTimed([string[]]$OllamaArgs, [int]$TimeoutSec) {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $cmd) { return -2 }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $cmd.Source
    $psi.Arguments = ($OllamaArgs -join " ")
    $psi.UseShellExecute = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    try {
        $p = [System.Diagnostics.Process]::Start($psi)
    } catch {
        return -2
    }
    if ($null -eq $p) { return -2 }
    if (-not $p.WaitForExit($TimeoutSec * 1000)) {
        try { $null = & taskkill.exe /PID $p.Id /T /F 2>$null } catch { }
        return -1
    }
    return $p.ExitCode
}

$pullTimeout = 180
if ("$env:CTB_OLLAMA_PULL_TIMEOUT" -match '^\d+$') { $pullTimeout = [int]$env:CTB_OLLAMA_PULL_TIMEOUT }

$base = Get-OllamaBase
$models = Get-OllamaModels $base

if ($ListOnly) {
    if ($null -eq $models) { Say "  닿지 않음: $base" "Yellow"; exit 0 }
    Say "  $base — 모델 $($models.Count)개" "Green"
    foreach ($n in $models) { Say "    $n" }
    exit 0
}

if ($null -eq $models) {
    Say "  Ollama가 꺼져 있습니다 — 나중에 켜면 됩니다. 켠 뒤 앱 설정 ▸ LLM 연결 ▸ Ollama에서 모델을 받을 수 있습니다." "Yellow"
    exit 0
}

if ($models -contains "gemma4:cloud") {
    Say "  이미 있습니다." "Green"
} else {
    Say "  없습니다. 등록합니다 (클라우드 모델 — 내려받는 파일 없음, 몇 초)…"
    $rc = Invoke-OllamaTimed @("pull", "gemma4:cloud") $pullTimeout
    if ($rc -eq 0) {
        Say "  쓰려면 앱 설정 ▸ LLM 연결 ▸ Ollama의 「로그인」. 로그인 없이 쓰려면 같은 자리 「모델 받기」에서 내 PC용 모델을 고르세요." "DarkGray"
    } elseif ($rc -eq -1) {
        Say "  $($pullTimeout)초 안에 끝나지 않아 멈췄습니다. 앱 설정 ▸ LLM 연결 ▸ Ollama의 「모델 받기」에서 고를 수 있습니다." "Yellow"
    } else {
        Say "  지금 등록하지 못했습니다. 앱 설정 ▸ LLM 연결 ▸ Ollama의 「모델 받기」에서 고를 수 있습니다." "Yellow"
    }
}

# 「판독 계획」(D-126)의 기본 모델은 kimi-k3:cloud — 종류 판정 벤치마크 1위(2026-09-11). 없으면 앱이 «자동»으로 내려간다.
if (-not ($models -contains "kimi-k3:cloud")) {
    Say "[5-1] 판독 계획 기본 모델 등록 (kimi-k3:cloud — 클라우드, 몇 초)…" "White"
    $rc = Invoke-OllamaTimed @("pull", "kimi-k3:cloud") $pullTimeout
    if ($rc -ne 0) { Say "  지금 등록하지 못했습니다. 판독 계획은 다른 비전 모델(자동)로 돕니다." "Yellow" }
}
exit 0
