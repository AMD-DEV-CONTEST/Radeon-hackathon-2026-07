<#
.SYNOPSIS
Install AetherDB as a loopback-only Windows validation service.

.DESCRIPTION
This advanced-operator helper is not the graphical installer and does not
enable hosted_bridge or full_server_deployment. Use the Tauri NSIS package for
the normal desktop application.
#>
[CmdletBinding()]
param(
    [string]$ServiceName = "AetherDBLocal",
    [ValidateRange(0, 65535)][int]$Port = 0,
    [string]$NssmPath = "",
    [string]$RuntimeRoot = "$env:ProgramData\AetherDB",
    [switch]$ReplaceExisting
)

$ErrorActionPreference = "Stop"
$ProjectPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$PythonPath = Join-Path $ProjectPath "venv\Scripts\python.exe"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]$identity
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-NssmExecutable {
    if ($NssmPath) {
        return (Resolve-Path -LiteralPath $NssmPath).Path
    }
    $command = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "NSSM is required. Install and verify it separately, then pass -NssmPath."
    }
    return $command.Source
}

function Get-AvailableLoopbackPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

function Assert-LoopbackPortAvailable([int]$Candidate) {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Candidate)
    try {
        $listener.Start()
    }
    catch {
        throw "Loopback port $Candidate is already in use."
    }
    finally {
        $listener.Stop()
    }
}

if (-not (Test-IsAdministrator)) {
    throw "Run this local service helper as Administrator."
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Project virtual environment is missing. Initialize it before installing the service."
}
if ($Port -eq 8000) {
    throw "Legacy fixed port 8000 is not allowed."
}
if ($Port -eq 0) {
    $Port = Get-AvailableLoopbackPort
}
Assert-LoopbackPortAvailable $Port

$NssmExecutable = Get-NssmExecutable
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing -and -not $ReplaceExisting) {
    throw "Service '$ServiceName' already exists. Pass -ReplaceExisting to replace it explicitly."
}
if ($existing) {
    & $NssmExecutable stop $ServiceName | Out-Null
    & $NssmExecutable remove $ServiceName confirm | Out-Null
}

$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$LogRoot = Join-Path $RuntimeRoot "logs"
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

$previousEnvironment = @{}
$runtimeEnvironment = @{
    AETHERDB_RESOURCE_ROOT = $ProjectPath
    AETHERDB_RUNTIME_ROOT = $RuntimeRoot
    AETHERDB_DEPLOYMENT_MODE = "local_desktop"
    AETHERDB_HOST = "127.0.0.1"
    AETHERDB_PORT = [string]$Port
    PYTHONUTF8 = "1"
}
try {
    foreach ($entry in $runtimeEnvironment.GetEnumerator()) {
        $previousEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, "Process")
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
    }
    & $PythonPath (Join-Path $ProjectPath "scripts\init_runtime.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime initialization failed."
    }
}
finally {
    foreach ($entry in $previousEnvironment.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
    }
}

& $NssmExecutable install $ServiceName $PythonPath (Join-Path $ProjectPath "main.py") | Out-Null
& $NssmExecutable set $ServiceName AppDirectory $ProjectPath | Out-Null
$serviceEnvironment = @(
    "AETHERDB_RESOURCE_ROOT=$ProjectPath"
    "AETHERDB_RUNTIME_ROOT=$RuntimeRoot"
    "AETHERDB_DEPLOYMENT_MODE=local_desktop"
    "AETHERDB_HOST=127.0.0.1"
    "AETHERDB_PORT=$Port"
    "PYTHONUNBUFFERED=1"
    "PYTHONUTF8=1"
)
& $NssmExecutable set $ServiceName AppEnvironmentExtra $serviceEnvironment | Out-Null
& $NssmExecutable set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $NssmExecutable set $ServiceName AppStdout (Join-Path $LogRoot "service.log") | Out-Null
& $NssmExecutable set $ServiceName AppStderr (Join-Path $LogRoot "service-error.log") | Out-Null
& $NssmExecutable set $ServiceName AppRotateFiles 1 | Out-Null
& $NssmExecutable set $ServiceName AppRotateBytes 10485760 | Out-Null
& $NssmExecutable set $ServiceName AppStopMethodSkip 0 | Out-Null
& $NssmExecutable set $ServiceName AppStopMethodConsole 30000 | Out-Null
& $NssmExecutable start $ServiceName | Out-Null

$ready = $false
$deadline = [DateTime]::UtcNow.AddSeconds(120)
while ([DateTime]::UtcNow -lt $deadline) {
    try {
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:$Port/api/auth/status" `
            -UseBasicParsing `
            -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $ready) {
    & $NssmExecutable stop $ServiceName | Out-Null
    throw "Service readiness timed out after 120 seconds. Inspect $LogRoot."
}

Write-Host "[OK] AetherDB local validation service is ready." -ForegroundColor Green
Write-Host "Endpoint: http://127.0.0.1:$Port"
Write-Host "Runtime:  $RuntimeRoot"
Write-Host "No public listener, firewall rule, API key output, or dependency download was created."
