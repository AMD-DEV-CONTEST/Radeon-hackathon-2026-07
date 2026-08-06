[CmdletBinding()]
param(
    [string]$VenvPath = ".venv-rocm",
    [string]$OutputRoot = "output\evidence\amd-demo-rocm",
    [int]$BatchSize = 4
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendRoot = Join-Path $repoRoot "backend"
$resolvedVenv = if ([System.IO.Path]::IsPathRooted($VenvPath)) {
    [System.IO.Path]::GetFullPath($VenvPath)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $VenvPath))
}
$colorgraph = Join-Path $resolvedVenv "Scripts\colorgraph.exe"
$resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
    [System.IO.Path]::GetFullPath($OutputRoot)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputRoot))
}

if (-not (Test-Path -LiteralPath $colorgraph)) {
    throw "ColorGraph ROCm environment is missing: $colorgraph"
}
if ($BatchSize -lt 1) {
    throw "BatchSize must be positive."
}
New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null

$precisionReport = Join-Path $resolvedOutput "precision-gate-rocm.json"
$rawBenchmark = Join-Path $resolvedOutput "amd-demo-raw-benchmark.json"
$auditReport = Join-Path $resolvedOutput "amd-demo-benchmark-audit.json"
$sourceManifest = Join-Path $repoRoot "output\evidence\bench-001-amd-demo-source\manifest.json"
$projectId = "amd-demo-snowdonia-12-5s-bd7a0a7dd9"

$env:COLORGRAPH_DEVICE = "rocm"
Push-Location $backendRoot
try {
    & $colorgraph doctor
    if ($LASTEXITCODE -ne 0) {
        throw "ColorGraph doctor failed."
    }
    & $colorgraph precision-gate `
        --require-runtime rocm `
        --repeats 3 `
        --output $precisionReport
    if ($LASTEXITCODE -ne 0) {
        throw "The ROCm precision gate failed."
    }
    & $colorgraph amd-demo-benchmark `
        $projectId `
        --source-manifest $sourceManifest `
        --benchmark-output $rawBenchmark `
        --output $auditReport `
        --batch-size $BatchSize
    if ($LASTEXITCODE -ne 0) {
        throw "The AMD Demo benchmark gate failed. Inspect $auditReport."
    }
} finally {
    Pop-Location
}

Write-Host "AMD Demo gate passed."
Write-Host "Audit: $auditReport"
Write-Host "Audit SHA-256: ${auditReport}.sha256"
