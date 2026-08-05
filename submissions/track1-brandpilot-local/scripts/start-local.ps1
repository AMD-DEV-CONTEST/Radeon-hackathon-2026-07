[CmdletBinding()]
param(
    [switch]$Production
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$frontendRoot = Join-Path $repoRoot "frontend"
$backendPython = Join-Path $backendRoot ".venv\Scripts\python.exe"

function Assert-PortAvailable([int]$Port) {
    $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    if ($listeners.Port -contains $Port) {
        throw "Port $Port is already in use. Stop the existing service and run this script again."
    }
}

function Stop-SpawnedProcessTree([System.Diagnostics.Process]$Process) {
    if (-not $Process) {
        return
    }
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($Process.Id)" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        $childProcess = Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
        if ($childProcess) {
            Stop-SpawnedProcessTree $childProcess
        }
    }
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
}

Assert-PortAvailable 3000
Assert-PortAvailable 8000

if (-not (Test-Path -LiteralPath $backendPython -PathType Leaf)) {
    throw "Backend virtual environment not found. Create backend\.venv and install backend\requirements.txt first."
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "node_modules") -PathType Container)) {
    throw "Frontend dependencies are missing. Run npm install in the frontend directory first."
}
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) {
    throw "npm.cmd was not found. Install Node.js 20 or newer and try again."
}

Push-Location $backendRoot
try {
    & $backendPython -c "import fastapi, uvicorn"
    $dependencyExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($dependencyExitCode -ne 0) {
    throw "Backend dependencies are incomplete. Activate backend\.venv and install requirements.txt."
}
if ($Production -and -not (Test-Path -LiteralPath (Join-Path $frontendRoot ".next\BUILD_ID") -PathType Leaf)) {
    throw "Production build not found. Run npm run build in the frontend directory first."
}

$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8000"
$env:BACKEND_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
$frontendCommand = if ($Production) { "start" } else { "dev" }

$backend = Start-Process -FilePath $backendPython -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $backendRoot -NoNewWindow -PassThru
$frontend = Start-Process -FilePath $npm.Source -ArgumentList "run", $frontendCommand -WorkingDirectory $frontendRoot -NoNewWindow -PassThru

try {
    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 500
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
        } catch {
            $health = $null
        }
    } until (($health.status -eq "ok") -or (Get-Date) -gt $deadline -or $backend.HasExited -or $frontend.HasExited)

    if ($health.status -ne "ok") {
        throw "Local services did not become ready within 30 seconds."
    }

    Write-Host "Frontend: http://localhost:3000"
    Write-Host "Backend docs: http://localhost:8000/docs"
    Write-Host "Health: http://localhost:8000/health"
    Write-Host "Press Ctrl+C to stop both local services."
    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    foreach ($process in @($frontend, $backend)) {
        if ($process -and -not $process.HasExited) {
            Stop-SpawnedProcessTree $process
        }
    }
}
