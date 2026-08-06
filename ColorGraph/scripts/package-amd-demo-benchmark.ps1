[CmdletBinding()]
param(
    [string]$ArchivePath = "output\evidence\colorgraph-amd-full-execution-package-v3.zip",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repoPrefix = $repoRoot.TrimEnd("\") + "\"

function Get-RepoRelativePath {
    param([string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Package input must remain inside the repository: $fullPath"
    }
    return $fullPath.Substring($repoPrefix.Length).Replace("\", "/")
}

$resolvedArchive = if ([System.IO.Path]::IsPathRooted($ArchivePath)) {
    [System.IO.Path]::GetFullPath($ArchivePath)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $ArchivePath))
}
$evidenceRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "output\evidence"))
if (-not $resolvedArchive.StartsWith($evidenceRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "ArchivePath must remain inside $evidenceRoot"
}
if (Test-Path -LiteralPath $resolvedArchive) {
    if (-not $Force) {
        throw "Archive already exists; pass -Force to replace this exact file: $resolvedArchive"
    }
    Remove-Item -LiteralPath $resolvedArchive
}

$manifestPath = Join-Path $evidenceRoot "amd-full-execution-package-v3-manifest.json"
$payloadRoots = @(
    "backend\data\projects\amd-demo-snowdonia-12-5s-bd7a0a7dd9",
    "backend\colorgraph",
    "backend\README.md",
    "backend\requirements-amd-rocm-linux-7.2.1.txt",
    "backend\requirements-amd-rocm-linux-radeon-cloud-7.2.1.txt",
    "backend\requirements-amd-rocm-windows-7.2.1.txt",
    "backend\pyproject.toml",
    "backend\uv.lock",
    "docs\AMD_DEMO_BENCHMARK.md",
    "tmp\radeon-cloud-template-amd-environment.md",
    "tmp\radeon-cloud-sshd-setup.md",
    "scripts\package-amd-demo-benchmark.ps1",
    "scripts\setup-amd-demo-rocm-windows.ps1",
    "scripts\setup-amd-demo-rocm-linux.sh",
    "scripts\run-amd-demo-benchmark.ps1",
    "scripts\run-amd-full-pipeline.ps1",
    "scripts\run-amd-full-pipeline-linux.sh",
    "output\evidence\bench-001-amd-demo-source\manifest.json",
    "output\evidence\bench-001-amd-demo-source\hard-cut-contact-sheet.png",
    "output\evidence\bench-001-amd-demo-source\tracked-mask-assets.json",
    "output\evidence\bench-001-amd-demo-prerequisite-audit.json",
    "output\evidence\bench-001-amd-demo-gate-audit.json",
    "output\evidence\bench-001-amd-demo-gate-audit.json.sha256",
    "output\evidence\bench-001-amd-demo-readiness.json",
    "output\evidence\bench-001-amd-rocm-environment-readiness.json"
)

$payloadFiles = foreach ($relativeRoot in $payloadRoots) {
    $absoluteRoot = Join-Path $repoRoot $relativeRoot
    if (-not (Test-Path -LiteralPath $absoluteRoot)) {
        throw "Required package input is missing: $relativeRoot"
    }
    $item = Get-Item -LiteralPath $absoluteRoot
    if ($item.PSIsContainer) {
        Get-ChildItem -LiteralPath $absoluteRoot -Recurse -File |
            Where-Object {
                $_.FullName -notmatch "\\__pycache__\\" -and
                $_.Extension -ne ".pyc"
            }
    } else {
        $item
    }
}
$payloadFiles = @($payloadFiles | Sort-Object FullName -Unique)
$fileRecords = foreach ($file in $payloadFiles) {
    $relative = Get-RepoRelativePath $file.FullName
    [pscustomobject][ordered]@{
        path = $relative
        bytes = $file.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
    }
}
$manifest = [ordered]@{
    schema_version = "colorgraph.amd-demo-execution-package/v3"
    created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    task_ids = @("CG-COLOR-003", "CG-BENCH-001")
    status = "validated_and_ready_for_transfer_to_supported_amd_rocm_host"
    project_id = "amd-demo-snowdonia-12-5s-bd7a0a7dd9"
    extraction_root = "ColorGraph repository root"
    payload_file_count = @($fileRecords).Count
    payload_bytes = ($fileRecords | Measure-Object -Property bytes -Sum).Sum
    payload_files = @($fileRecords)
    runbook = "docs/AMD_DEMO_BENCHMARK.md"
    setup_script = "scripts/setup-amd-demo-rocm-windows.ps1"
    execution_script = "scripts/run-amd-full-pipeline.ps1"
    setup_scripts = [ordered]@{
        windows = "scripts/setup-amd-demo-rocm-windows.ps1"
        linux = "scripts/setup-amd-demo-rocm-linux.sh"
    }
    execution_scripts = [ordered]@{
        windows = "scripts/run-amd-full-pipeline.ps1"
        linux = "scripts/run-amd-full-pipeline-linux.sh"
    }
    note = "This package was validated on Radeon Cloud but contains no copied AMD result or model weights; every target host must still generate its own fresh audit with the frozen local model caches."
}
$manifestJson = $manifest | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText(
    $manifestPath,
    "$manifestJson`n",
    [System.Text.UTF8Encoding]::new($false)
)

$archiveInputs = @($fileRecords | ForEach-Object { $_.path }) + @(
    Get-RepoRelativePath $manifestPath
)
New-Item -ItemType Directory -Path ([System.IO.Path]::GetDirectoryName($resolvedArchive)) -Force |
    Out-Null
Push-Location $repoRoot
try {
    & tar.exe -a -c -f $resolvedArchive @archiveInputs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the AMD Demo execution package."
    }
} finally {
    Pop-Location
}

$archiveDigest = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedArchive).Hash.ToLowerInvariant()
$sidecarPath = "$resolvedArchive.sha256"
[System.IO.File]::WriteAllText(
    $sidecarPath,
    "$archiveDigest  $([System.IO.Path]::GetFileName($resolvedArchive))`n",
    [System.Text.UTF8Encoding]::new($false)
)
$manifestDigest = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant()
$entries = @(& tar.exe -tf $resolvedArchive)
if ($LASTEXITCODE -ne 0) {
    throw "Failed to inspect the generated AMD Demo execution package."
}

[pscustomobject]@{
    Archive = $resolvedArchive
    ArchiveBytes = (Get-Item -LiteralPath $resolvedArchive).Length
    ArchiveSHA256 = $archiveDigest
    ArchiveEntries = $entries.Count
    Manifest = $manifestPath
    ManifestSHA256 = $manifestDigest
    PayloadFiles = @($fileRecords).Count
    PayloadBytes = $manifest.payload_bytes
} | ConvertTo-Json -Depth 3
