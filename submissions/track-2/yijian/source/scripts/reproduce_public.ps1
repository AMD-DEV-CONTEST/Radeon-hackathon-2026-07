param(
    [switch]$InstallBrowser,
    [switch]$Serve
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runId = [Guid]::NewGuid().ToString("N")
$venv = Join-Path ([System.IO.Path]::GetTempPath()) "yijian-public-repro-$runId"
$report = Join-Path ([System.IO.Path]::GetTempPath()) "yijian-public-reproduction-report-$runId.json"

try {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.13 -m venv $venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c "import sys; assert sys.version_info[:2] == (3, 13), sys.version"
        if ($LASTEXITCODE -ne 0) { throw "Python 3.13 was not found." }
        & python -m venv $venv
    } else {
        throw "Python 3.13 was not found."
    }
    if ($LASTEXITCODE -ne 0) { throw "Clean virtual environment creation failed." }

    $python = Join-Path $venv (Join-Path "Scripts" "python.exe")
    & $python -m pip install --disable-pip-version-check -r (Join-Path $root "requirements-lock.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

    if ($InstallBrowser) {
        & $python -m playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw "Chromium installation failed." }
    }

    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $validator = Join-Path $root (Join-Path "scripts" "validate_public_submission_snapshot.py")
    & $python $validator --snapshot $root --output $report
    if ($LASTEXITCODE -ne 0) { throw "Public snapshot validation failed. See $report" }

    Write-Host "YIJIAN PUBLIC REPRODUCTION: PASS" -ForegroundColor Green
    Write-Host "Report: $report"

    if ($Serve) {
        & $python -m uvicorn app:app --app-dir (Join-Path $root "backend") --host 127.0.0.1 --port 8000
    } else {
        Write-Host "Re-run this command with -Serve to start the verified UI."
    }
} finally {
    if (Test-Path -LiteralPath $venv) {
        Remove-Item -LiteralPath $venv -Recurse -Force
    }
}
