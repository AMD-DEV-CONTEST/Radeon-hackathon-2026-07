# BotverseX Windows demo launcher (Reachy Mini presentation machine)
# Usage:
#   .\scripts\windows\dev-all.ps1 up
#   .\scripts\windows\dev-all.ps1 down
#   .\scripts\windows\dev-all.ps1 status
param(
    [ValidateSet("up", "down", "status")]
    [string]$Command = "up"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$WebLog = Join-Path $env:TEMP "botversex_web.log"
$Npm = Join-Path $env:ProgramFiles "nodejs\npm.cmd"
if (-not (Test-Path $Npm)) { $Npm = "npm.cmd" }

function Invoke-DevUp {
    & "$Root\scripts\windows\dev-up.ps1" $Command
    if ($Command -ne "up") { return }

    Write-Host "[dev-all] starting web (5173) -> $WebLog"
    Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "vite" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

    $webJob = Start-Process -FilePath $Npm `
        -ArgumentList @("--prefix", "$Root\apps\web", "run", "dev", "--", "--host", "0.0.0.0") `
        -RedirectStandardOutput $WebLog `
        -RedirectStandardError (Join-Path $env:TEMP "botversex_web.err.log") `
        -PassThru -WindowStyle Hidden

    Write-Host "[dev-all] waiting for web ..."
    for ($i = 1; $i -le 25; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400) {
                Write-Host "[dev-all] web up after ${i}s (pid $($webJob.Id))"
                break
            }
        } catch { }
    }
    & "$Root\scripts\windows\dev-all.ps1" status
}

switch ($Command) {
    "up" { Invoke-DevUp }
    "down" {
        Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match "vite" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        & "$Root\scripts\windows\dev-up.ps1" down
    }
    "status" {
        Write-Host "== web =="
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing -TimeoutSec 3 | Out-Null
            Write-Host "web: up (http://127.0.0.1:5173)"
        } catch {
            Write-Host "web: down"
        }
        Write-Host ""
        & "$Root\scripts\windows\dev-up.ps1" status
    }
}
