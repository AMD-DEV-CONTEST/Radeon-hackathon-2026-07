param([switch]$DemoMode)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root "data\run"
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$StopScript = Join-Path $PSScriptRoot "stop-all.ps1"
if (Test-Path $StopScript) { powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StopScript | Out-Null }

function Start-IndusProcess($Name, $FilePath, $Arguments, $WorkingDirectory) {
    $Info = [System.Diagnostics.ProcessStartInfo]::new()
    if ([System.IO.Path]::GetExtension($FilePath) -ieq ".cmd") {
        $Info.FileName = "$env:SystemRoot\System32\cmd.exe"
        $Command = '"' + $FilePath + '" ' + (($Arguments | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' }) -join ' ')
        $Info.Arguments = '/d /c "' + $Command + '"'
    } else {
        $Info.FileName = $FilePath
        $Info.Arguments = (($Arguments | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' }) -join ' ')
    }
    $Info.WorkingDirectory = $WorkingDirectory
    $Info.UseShellExecute = $true
    $Info.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $Process = [System.Diagnostics.Process]::Start($Info)
    Set-Content -LiteralPath (Join-Path $RunDir "$Name.pid") -Value $Process.Id
    Write-Host "Started $Name (PID $($Process.Id))"
}

$Python = $null
if (Test-Path (Join-Path $Root ".venv\Scripts\python.exe")) {
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
} elseif (Test-Path (Join-Path $Root "ai-service\.venv\Scripts\python.exe")) {
    $Python = Join-Path $Root "ai-service\.venv\Scripts\python.exe"
} else {
    $SysPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($SysPython) { $Python = $SysPython.Source }
    else { throw "Python not found. Please make sure Python is installed and in PATH." }
}

Write-Host "Using Python: $Python" -ForegroundColor Cyan

# Start unified FastAPI backend (replaces legacy Java backend + Python ai-service)
Start-IndusProcess "backend" $Python @("-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", "8000") $Root

# Start React frontend
$Npm = (Get-Command npm.cmd -ErrorAction Stop).Source
Start-IndusProcess "frontend" $Npm @("run", "dev", "--", "--host", "127.0.0.1") (Join-Path $Root "frontend")

Write-Host "Waiting for services..."
$Healthy = $false
for ($Attempt = 1; $Attempt -le 30; $Attempt++) {
    Start-Sleep -Seconds 3
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "health-check.ps1")
    if ($LASTEXITCODE -eq 0) { $Healthy = $true; break }
}
if (-not $Healthy) { throw "One or more services did not become healthy. Check logs and try health-check.ps1." }
Write-Host "Open http://localhost:5173" -ForegroundColor Green
