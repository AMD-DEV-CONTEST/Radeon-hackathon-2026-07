# BotverseX Windows — API (8000) + Realtime (8002)
param(
    [ValidateSet("up", "down", "status")]
    [string]$Command = "up"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$ApiPy = Join-Path $Root "apps\api\.venv\Scripts\python.exe"
$RtPy = Join-Path $Root "apps\realtime\.venv\Scripts\python.exe"
$ApiLog = Join-Path $env:TEMP "botversex_api.log"
$RtLog = Join-Path $env:TEMP "botversex_realtime.log"

# Reachy demo defaults — override in $PROFILE or System env
if (-not $env:BOTVERSEX_ROBOTS_CONFIG) {
    $env:BOTVERSEX_ROBOTS_CONFIG = Join-Path $Root "apps\realtime\config\robots.windows-demo.json"
}
if (-not $env:REACHY_MINI_SDK_PATH) {
    $env:REACHY_MINI_SDK_PATH = "C:\Users\AMD\sdk\reachy_mini_Allan"
}
if (-not $env:BOTVERSEX_SEEED_CONVERSATION_DIR) {
    $env:BOTVERSEX_SEEED_CONVERSATION_DIR = "$env:USERPROFILE\.local\share\botversex\seeed_reachymini_conversation"
}
if (-not $env:BOTVERSEX_SEEED_KEYS_FILE) {
    $env:BOTVERSEX_SEEED_KEYS_FILE = "$env:USERPROFILE\.config\botversex\reachy_seeed_keys.json"
}

function Stop-Port($Port) {
    Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
}

function Stop-ByCommandLine($Pattern) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $Pattern } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

switch ($Command) {
    "down" {
        Write-Host "[dev-up] stopping ..."
        Stop-ByCommandLine "uvicorn app.main:app --port 8000"
        Stop-ByCommandLine "run_api.py"
        Stop-Port 8000
        Stop-Port 8002
        Write-Host "[dev-up] stopped."
    }
    "status" {
        Write-Host "== /api/setup/health =="
        try {
            (Invoke-WebRequest -Uri "http://127.0.0.1:8002/api/setup/health" -UseBasicParsing -TimeoutSec 5).Content
        } catch { Write-Host "realtime: down" }
        Write-Host ""
        Write-Host "== env =="
        Write-Host "BOTVERSEX_ROBOTS_CONFIG=$($env:BOTVERSEX_ROBOTS_CONFIG)"
        Write-Host "REACHY_MINI_SDK_PATH=$($env:REACHY_MINI_SDK_PATH)"
    }
    "up" {
        if (-not (Test-Path $ApiPy)) {
            Write-Error "Missing $ApiPy — run scripts\windows\setup-first.ps1"
        }
        if (-not (Test-Path $RtPy)) {
            Write-Error "Missing $RtPy — run scripts\windows\setup-first.ps1"
        }
        & $PSScriptRoot\dev-up.ps1 down
        New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\AppData\Local\Temp" | Out-Null

        Write-Host "[dev-up] API (8000) -> $ApiLog"
        Start-Process -FilePath $ApiPy `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--port", "8000", "--app-dir", ".") `
            -WorkingDirectory (Join-Path $Root "apps\api") `
            -RedirectStandardOutput $ApiLog `
            -RedirectStandardError (Join-Path $env:TEMP "botversex_api.err.log") `
            -WindowStyle Hidden | Out-Null

        Write-Host "[dev-up] Realtime (8002) -> $RtLog"
        Start-Process -FilePath $RtPy `
            -ArgumentList @((Join-Path $Root "apps\realtime\run_api.py"), "--http") `
            -WorkingDirectory $Root `
            -RedirectStandardOutput $RtLog `
            -RedirectStandardError (Join-Path $env:TEMP "botversex_realtime.err.log") `
            -WindowStyle Hidden | Out-Null

        Write-Host "[dev-up] waiting ..."
        for ($i = 1; $i -le 25; $i++) {
            Start-Sleep -Seconds 1
            $okApi = $false
            $okRt = $false
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2
                $okApi = $r.StatusCode -ge 200 -and $r.StatusCode -lt 400
            } catch { }
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:8002/api/setup/health" -UseBasicParsing -TimeoutSec 2
                $okRt = $r.StatusCode -ge 200 -and $r.StatusCode -lt 400
            } catch { }
            if ($okApi -and $okRt) {
                Write-Host "[dev-up] both up after ${i}s"
                break
            }
        }
        & $PSScriptRoot\dev-up.ps1 status
    }
}
