param(
    [string]$OrchestratorUrl = $env:ORCHESTRATOR_URL,
    [string]$AgentType = $env:AGENT_TYPE,
    [string]$Name = $env:WORKER_NAME,
    [string]$WorkspaceRoot = $env:WORKSPACE_ROOT,
    [int]$MaxConcurrency = 1
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Expected worker Python at $Python. Create the venv before starting the worker."
}

$ArgsList = @()
if ($OrchestratorUrl) { $ArgsList += @("--orchestrator-url", $OrchestratorUrl) }
if ($AgentType) { $ArgsList += @("--agent-type", $AgentType) }
if ($Name) { $ArgsList += @("--name", $Name) }
if ($WorkspaceRoot) { $ArgsList += @("--workspace-root", $WorkspaceRoot) }
$ArgsList += @("--max-concurrency", "$MaxConcurrency", "run")

& $Python (Join-Path $ProjectRoot "worker\worker_cli.py") @ArgsList
