[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]] $DeployArguments
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Stop-Deployment {
    param([Parameter(Mandatory = $true)][string] $Message)
    [Console]::Error.WriteLine("ERROR: $Message")
    exit 1
}

$pythonExecutable = $null
$pythonPrefixArguments = @()
$pythonLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
if ($null -ne $pythonLauncher) {
    & $pythonLauncher.Source -3 -c `
        "import sys; raise SystemExit(sys.version_info < (3, 11))"
    if ($LASTEXITCODE -eq 0) {
        $pythonExecutable = $pythonLauncher.Source
        $pythonPrefixArguments = @("-3")
    }
}
if ($null -eq $pythonExecutable) {
    $pythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        Stop-Deployment "Python 3.11 or newer is required."
    }
    & $pythonCommand.Source -c `
        "import sys; raise SystemExit(sys.version_info < (3, 11))"
    if ($LASTEXITCODE -ne 0) {
        Stop-Deployment "Python 3.11 or newer is required."
    }
    $pythonExecutable = $pythonCommand.Source
}

& $pythonExecutable @pythonPrefixArguments `
    (Join-Path $PSScriptRoot "deploy\deploy.py") `
    @DeployArguments
$deploymentExitCode = $LASTEXITCODE
if ($deploymentExitCode -ne 0) {
    exit $deploymentExitCode
}
