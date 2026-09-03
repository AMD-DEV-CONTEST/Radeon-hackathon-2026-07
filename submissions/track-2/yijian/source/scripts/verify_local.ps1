param(
    [switch]$SkipUi,
    [switch]$RequireLocalMentor
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    Write-Host "[1/5] Python tests"
    & py -3 -m pytest backend/tests -q
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed." }

    Write-Host "[2/5] Go rules cross-check"
    & node backend/tests/crosscheck.mjs backend/tests/recommendation-smoke.sgf
    if ($LASTEXITCODE -ne 0) { throw "Go rules cross-check failed." }

    Write-Host "[3/5] Backend health"
    $deadline = (Get-Date).AddSeconds(30)
    do {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8600/api/health" -TimeoutSec 2
        } catch {
            $health = $null
        }
        if ($health -and $health.status -eq "ok") { break }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    if (-not $health) { throw "GoMentor backend is not available on port 8600." }
    if ($health.demo -eq $true -or $health.engine -ne "katago") {
        throw "Real KataGo is required for local acceptance."
    }

    Write-Host "[4/5] Mentor capability"
    $mentor = Invoke-RestMethod -Uri "http://127.0.0.1:8600/api/mentor/status?force=true" -TimeoutSec 5
    if (-not $mentor.offlineReady) { throw "The deterministic mentor fallback is not ready." }
    $local = $mentor.modes | Where-Object { $_.id -eq "local" }
    if ($RequireLocalMentor -and -not $local.ready) {
        throw "The local Qwen mentor is required but not ready."
    }

    if (-not $SkipUi) {
        Write-Host "[5/5] Browser acceptance"
        & py -3 backend/tests/ui_check.py runtime/validation
        if ($LASTEXITCODE -ne 0) { throw "Browser acceptance failed." }
    } else {
        Write-Host "[5/5] Browser acceptance skipped"
    }

    Write-Host "Local acceptance passed."
    Write-Host "KataGo: $($health.katagoVersion) / $($health.backend)"
    Write-Host "Local mentor ready: $($local.ready)"
} finally {
    Pop-Location
}
