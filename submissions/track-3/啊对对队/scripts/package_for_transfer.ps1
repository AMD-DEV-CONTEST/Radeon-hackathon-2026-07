$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProjectParent = Split-Path -Parent $ProjectRoot
$ProjectName = Split-Path -Leaf $ProjectRoot
$Artifacts = Join-Path $ProjectRoot "artifacts"
New-Item -ItemType Directory -Path $Artifacts -Force | Out-Null
$Artifacts = (Resolve-Path -LiteralPath $Artifacts).Path

if (-not $Artifacts.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Artifacts directory is outside the project root"
}

$Archive = Join-Path $Artifacts "parcel-sorter-rocm-gpu-ready-v0.2.0.tar.gz"
$ChecksumFile = Join-Path $Artifacts "SHA256SUMS.txt"
$Tar = Get-Command tar.exe -ErrorAction Stop

if (Test-Path $Archive) {
    Remove-Item -LiteralPath $Archive -Force
}

& $Tar.Source `
    -czf $Archive `
    --exclude="$ProjectName/.venv" `
    --exclude="$ProjectName/artifacts" `
    --exclude="$ProjectName/datasets" `
    --exclude="$ProjectName/checkpoints" `
    --exclude="$ProjectName/outputs" `
    --exclude="$ProjectName/__pycache__" `
    -C $ProjectParent `
    $ProjectName

if ($LASTEXITCODE -ne 0) {
    throw "tar failed with exit code $LASTEXITCODE"
}

$Hash = Get-FileHash -LiteralPath $Archive -Algorithm SHA256
"$($Hash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($Archive))" |
    Set-Content -LiteralPath $ChecksumFile -Encoding ascii

Get-Item -LiteralPath $Archive | Select-Object FullName,Length,LastWriteTime
Get-Content -LiteralPath $ChecksumFile
