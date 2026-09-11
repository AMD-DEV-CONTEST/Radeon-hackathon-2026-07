param(
    [switch]$IncludeLeRobot
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ThirdPartyRoot = Join-Path $ProjectRoot "third_party"
New-Item -ItemType Directory -Path $ThirdPartyRoot -Force | Out-Null
$ThirdPartyRoot = (Resolve-Path -LiteralPath $ThirdPartyRoot).Path
if (-not $ThirdPartyRoot.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Third-party directory is outside the project root"
}

function Install-SourceArchive {
    param(
        [string]$Name,
        [string]$Repository,
        [string]$Revision
    )

    $Destination = Join-Path $ThirdPartyRoot $Name
    $Marker = Join-Path $Destination ".upstream-sha"
    $DestinationFullPath = [System.IO.Path]::GetFullPath($Destination)
    if (-not $DestinationFullPath.StartsWith($ThirdPartyRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to manage a source directory outside third_party"
    }
    if ((Test-Path $Marker) -and ((Get-Content -Raw $Marker).Trim() -eq $Revision)) {
        Write-Host "$Name is already pinned at $Revision"
        return
    }

    $Archive = Join-Path $ThirdPartyRoot "$Name-$Revision.zip"
    $ExtractRoot = Join-Path $ThirdPartyRoot "_$Name-extract"
    Invoke-WebRequest -UseBasicParsing `
        -Uri "https://api.github.com/repos/$Repository/zipball/$Revision" `
        -Headers @{"User-Agent"="Parcel-Sorter-ROCm"} `
        -OutFile $Archive

    if (Test-Path $ExtractRoot) {
        Remove-Item -LiteralPath $ExtractRoot -Recurse -Force
    }
    Expand-Archive -LiteralPath $Archive -DestinationPath $ExtractRoot
    $Expanded = Get-ChildItem -LiteralPath $ExtractRoot -Directory | Select-Object -First 1
    if ($null -eq $Expanded) {
        throw "Archive for $Name did not contain a source directory"
    }
    if (Test-Path $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    Move-Item -LiteralPath $Expanded.FullName -Destination $Destination
    Set-Content -LiteralPath $Marker -Value $Revision -Encoding ascii
    Remove-Item -LiteralPath $ExtractRoot -Recurse -Force
    Remove-Item -LiteralPath $Archive -Force
    Write-Host "Downloaded $Name at $Revision"
}

Install-SourceArchive `
    -Name "genesis-world" `
    -Repository "Genesis-Embodied-AI/genesis-world" `
    -Revision "ec0efcc0daf9b9932920e6b73f5f810961330997"

if ($IncludeLeRobot) {
    Install-SourceArchive `
        -Name "lerobot" `
        -Repository "huggingface/lerobot" `
        -Revision "73dbb6f43a5088583706c91fb73c6957bca5f806"
}
