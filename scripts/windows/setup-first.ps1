# First-time setup on Windows demo machine (Run in PowerShell as normal user)
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#   cd C:\Users\Public\dev\botversex
#   .\scripts\windows\setup-first.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

Write-Host "== BotverseX Windows demo setup =="
Write-Host "ROOT=$Root"

function Require-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Error "Missing $Name. Install Node 20+ and Python 3.12+ first."
    }
}

Require-Command node
Require-Command npm
Require-Command python

Write-Host "[1/4] web npm install ..."
Push-Location (Join-Path $Root "apps\web")
npm install
Pop-Location

Write-Host "[2/4] api venv ..."
$ApiVenv = Join-Path $Root "apps\api\.venv"
if (-not (Test-Path $ApiVenv)) { python -m venv $ApiVenv }
& "$ApiVenv\Scripts\pip.exe" install -r (Join-Path $Root "apps\api\requirements.txt")

Write-Host "[3/4] realtime venv ..."
$RtVenv = Join-Path $Root "apps\realtime\.venv"
if (-not (Test-Path $RtVenv)) { python -m venv $RtVenv }
& "$RtVenv\Scripts\pip.exe" install -r (Join-Path $Root "apps\realtime\requirements.txt")

Write-Host "[4/4] demo dirs ..."
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\sdk" | Out-Null
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.config\botversex" | Out-Null

Write-Host ""
Write-Host "Next steps:"
Write-Host "  1) Reachy SDK synced to $env:USERPROFILE\sdk\reachy_mini_Allan (or clone there)"
Write-Host "  2) Copy apps\api\.env from dev machine (API keys)"
Write-Host "  3) Copy reachy_seeed_keys.json to $env:USERPROFILE\.config\botversex\"
Write-Host "  4) Edit apps\realtime\config\robots.windows-demo.json if SDK path differs"
Write-Host "  5) .\scripts\windows\dev-all.ps1 up"
Write-Host "  6) Browser: http://127.0.0.1:5173/robots/reachy_mini"
