<#
.SYNOPSIS
Remove the AetherDB local validation service while retaining user data.
#>
[CmdletBinding()]
param(
    [string]$ServiceName = "AetherDBLocal",
    [string]$NssmPath = "",
    [string]$RuntimeRoot = "$env:ProgramData\AetherDB"
)

$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this service removal helper as Administrator."
}

if ($NssmPath) {
    $NssmExecutable = (Resolve-Path -LiteralPath $NssmPath).Path
}
else {
    $command = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "NSSM is required. Pass the verified executable with -NssmPath."
    }
    $NssmExecutable = $command.Source
}

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $service) {
    Write-Host "Service '$ServiceName' is not installed."
    exit 0
}

& $NssmExecutable stop $ServiceName | Out-Null
$deadline = [DateTime]::UtcNow.AddSeconds(30)
while ([DateTime]::UtcNow -lt $deadline) {
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service -or $service.Status -eq "Stopped") {
        break
    }
    Start-Sleep -Milliseconds 250
}
& $NssmExecutable remove $ServiceName confirm | Out-Null

Write-Host "[OK] Service '$ServiceName' was removed." -ForegroundColor Green
Write-Host "Runtime data was retained at: $([IO.Path]::GetFullPath($RuntimeRoot))"
Write-Host "Data removal is a separate, explicit operator action and is never performed by this script."
