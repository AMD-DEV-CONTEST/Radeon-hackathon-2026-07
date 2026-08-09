$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Write-Host "IndusMind AI setup" -ForegroundColor Cyan

if (-not (Get-Command java -ErrorAction SilentlyContinue)) { throw "Java 21+ is required." }
$MavenCmd = Get-Command mvn -ErrorAction SilentlyContinue
if (-not $MavenCmd -and -not (Test-Path "C:\apache-maven-3.9.12\apache-maven-3.9.12\bin\mvn.cmd")) { throw "Maven is required." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js LTS is required." }

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Py = Get-Command py -ErrorAction SilentlyContinue
    if ($Py) { $PythonExe = "py"; $PythonArgs = @("-3.11") }
    else { throw "Python 3.11+ is required. Install it and enable Add Python to PATH." }
} else {
    $PythonExe = "python"; $PythonArgs = @()
}

Push-Location "$Root\frontend"
try {
    & npm.cmd install
    & npm.cmd run build
} finally { Pop-Location }

Push-Location "$Root\ai-service"
try {
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        & $PythonExe @PythonArgs -m venv .venv
    }
    & ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
} finally { Pop-Location }

if ($MavenCmd) { $MavenExe = $MavenCmd.Source }
else { $MavenExe = "C:\apache-maven-3.9.12\apache-maven-3.9.12\bin\mvn.cmd" }

Push-Location "$Root\backend"
try { & $MavenExe test } finally { Pop-Location }

Write-Host "Setup complete. Run scripts\start-all.ps1 -DemoMode" -ForegroundColor Green

