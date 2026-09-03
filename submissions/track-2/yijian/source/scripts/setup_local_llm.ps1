param(
    [switch]$SkipRuntimeInstall,
    [string]$ModelUrl = "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf?download=true"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$modelDir = Join-Path $projectRoot "runtime\models"
$modelPath = Join-Path $modelDir "Qwen3-4B-Q4_K_M.gguf"
$expectedModelBytes = [int64]2497280256
$expectedModelSha256 = "7485FE6F11AF29433BC51CAB58009521F205840F5B4AE3A32FA7F92E8534FDF5"
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null

function Download-File([string]$Url, [string]$Destination) {
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -L --fail --retry 3 --retry-delay 2 --continue-at - `
            --output $Destination $Url
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    } else {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
    }
}

function Find-LlamaServer {
    $bundled = Join-Path $projectRoot "runtime\llm\llama-server.exe"
    if (Test-Path -LiteralPath $bundled) { return $bundled }
    $command = Get-Command llama-server.exe,llama-server -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    $wingetLink = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\llama-server.exe"
    if (Test-Path -LiteralPath $wingetLink) { return $wingetLink }
    return $null
}

function Test-ModelFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -ne $expectedModelBytes) { return $false }
    Write-Host "Verifying the official model SHA-256..."
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash -eq $expectedModelSha256
}

$server = Find-LlamaServer
if (-not $server -and -not $SkipRuntimeInstall) {
    Write-Host "[1/3] Downloading the official llama.cpp CUDA runtime..."
    $runtimeDir = Join-Path $projectRoot "runtime\llm"
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $release = Invoke-RestMethod -UseBasicParsing -Headers @{"User-Agent"="Yijian-GoMentor"} `
        -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
    $mainAsset = $release.assets | Where-Object {
        $_.name -match 'bin-win-cuda-12\.4-x64\.zip$' -and $_.name -notmatch '^cudart-'
    } | Select-Object -First 1
    $cudaAsset = $release.assets | Where-Object {
        $_.name -match '^cudart-.*bin-win-cuda-12\.4-x64\.zip$'
    } | Select-Object -First 1
    if (-not $mainAsset) {
        throw "The latest llama.cpp release has no Windows CUDA 12.4 asset."
    }
    $mainZip = Join-Path $runtimeDir "llama-cuda.zip"
    Download-File $mainAsset.browser_download_url $mainZip
    Expand-Archive -LiteralPath $mainZip -DestinationPath $runtimeDir -Force
    Remove-Item -LiteralPath $mainZip
    if ($cudaAsset) {
        $cudaZip = Join-Path $runtimeDir "llama-cudart.zip"
        Download-File $cudaAsset.browser_download_url $cudaZip
        Expand-Archive -LiteralPath $cudaZip -DestinationPath $runtimeDir -Force
        Remove-Item -LiteralPath $cudaZip
    }
    $server = Find-LlamaServer
}
if (-not $server) {
    throw "llama-server was not found. Install llama.cpp and run this script again."
}

if (Test-ModelFile $modelPath) {
        Write-Host "[2/3] Model already exists: $modelPath"
} else {
    if (Test-Path -LiteralPath $modelPath) {
        Write-Host "The existing model failed integrity verification and will be downloaded again."
        Remove-Item -LiteralPath $modelPath
    }
    Write-Host "[2/3] Downloading Qwen3-4B Q4 (about 2.5 GB, one time only)..."
    $partial = "$modelPath.partial"
    $partialReady = Test-ModelFile $partial
    if (-not $partialReady) {
        if ((Test-Path -LiteralPath $partial) -and (Get-Item -LiteralPath $partial).Length -ge $expectedModelBytes) {
            Remove-Item -LiteralPath $partial
        }
        Download-File $ModelUrl $partial
    }
    if (-not (Test-ModelFile $partial)) {
        throw "The model download failed integrity verification. Partial file kept at: $partial"
    }
    Move-Item -LiteralPath $partial -Destination $modelPath
}

Write-Host "[3/3] Installation complete."
Write-Host "Model: $modelPath"
Write-Host "Runtime: $server"
Write-Host "The GoMentor launcher will start the offline mentor automatically."
