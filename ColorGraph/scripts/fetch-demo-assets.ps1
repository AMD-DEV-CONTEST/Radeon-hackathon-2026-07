[CmdletBinding()]
param(
    [ValidateSet("all", "tbilisi", "snowdonia")]
    [string]$Asset = "all",

    [string]$Destination = (Join-Path $PSScriptRoot "..\demo-assets"),

    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$destinationRoot = [System.IO.Path]::GetFullPath($Destination)

$assets = @(
    [PSCustomObject]@{
        Id = "tbilisi"
        FileName = "tbilisi-night-canon-eos-m3.ogv"
        Uri = "https://upload.wikimedia.org/wikipedia/commons/b/ba/Tbilisi_life_-_Georgia_Travel_-_canon_camera_Eosm11_-_Creative_commons.ogv"
        Sha256 = "2c21780225809981c78b94cf6d9cc0e3aa6449e1ad989215cf8134f2b08600e7"
        Credit = "Tbilisi life at night - Mostafameraji - CC BY-SA 4.0"
    },
    [PSCustomObject]@{
        Id = "snowdonia"
        FileName = "snowdonia-dji-fc200.webm"
        Uri = "https://upload.wikimedia.org/wikipedia/commons/9/90/Snowdonia_by_drone.webm"
        Sha256 = "e6ff1c365a4e86576678d8b4b2bf13fed25e465c11f6ccb4615131befa6e7309"
        Credit = "Snowdonia by drone - Wiebe de Jager - CC BY-SA 4.0"
    }
)

$selectedAssets = if ($Asset -eq "all") {
    $assets
} else {
    $assets | Where-Object { $_.Id -eq $Asset }
}

if (-not (Test-Path -LiteralPath $destinationRoot)) {
    if ($VerifyOnly) {
        throw "Demo asset directory does not exist: $destinationRoot"
    }
    New-Item -ItemType Directory -Path $destinationRoot | Out-Null
}

foreach ($item in $selectedAssets) {
    $target = Join-Path $destinationRoot $item.FileName
    if (Test-Path -LiteralPath $target) {
        $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -eq $item.Sha256) {
            Write-Host "Verified $($item.FileName)"
            Write-Host "  $($item.Credit)"
            continue
        }
        if ($VerifyOnly) {
            throw "SHA-256 mismatch for $target. Expected $($item.Sha256), got $actual"
        }
    } elseif ($VerifyOnly) {
        throw "Missing demo asset: $target"
    }

    $temporary = Join-Path $destinationRoot (".{0}.{1}.download" -f $item.FileName, [guid]::NewGuid().ToString("N"))
    try {
        Write-Host "Downloading $($item.FileName)"
        Invoke-WebRequest -UseBasicParsing -Uri $item.Uri -OutFile $temporary
        $actual = (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $item.Sha256) {
            throw "SHA-256 mismatch for downloaded $($item.FileName). Expected $($item.Sha256), got $actual"
        }
        Move-Item -LiteralPath $temporary -Destination $target -Force
        Write-Host "Verified $($item.FileName)"
        Write-Host "  $($item.Credit)"
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

Write-Host "Demo assets ready in $destinationRoot"
