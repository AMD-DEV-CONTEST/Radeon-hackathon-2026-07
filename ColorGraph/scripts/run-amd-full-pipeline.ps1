[CmdletBinding()]
param(
    [string]$VenvPath = ".venv-rocm",
    [string]$OutputRoot = "output\evidence\amd-full-rocm",
    [string]$ProjectId = "amd-demo-snowdonia-12-5s-bd7a0a7dd9",
    [string]$OllamaRuntimeVersion = "0.20.6",
    [string]$OllamaServerLog = "",
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
$venvPython = Join-Path $resolvedVenv "Scripts\python.exe"
$resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
    [System.IO.Path]::GetFullPath($OutputRoot)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputRoot))
}

if (-not (Test-Path -LiteralPath $colorgraph)) {
    throw "ColorGraph ROCm environment is missing: $colorgraph"
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "ROCm Python is missing: $venvPython"
}
if ($BatchSize -lt 1) {
    throw "BatchSize must be positive."
}
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama was not found on PATH."
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "FFmpeg was not found on PATH."
}

$ollamaVersion = try {
    (Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 5).version
} catch {
    throw "The local Ollama service is unavailable. Start it before running this gate."
}
if ($ollamaVersion -ne $OllamaRuntimeVersion) {
    throw "Ollama runtime mismatch: expected $OllamaRuntimeVersion, observed $ollamaVersion."
}
$ollamaTags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 10
$pinnedModels = @(
    $ollamaTags.models | Where-Object {
        ($_.name -eq "colorgraph-qwen3.5:9b") -or
        ($_.model -eq "colorgraph-qwen3.5:9b")
    }
)
if ($pinnedModels.Count -ne 1) {
    throw "The pinned Ollama model colorgraph-qwen3.5:9b was not found exactly once."
}
$expectedOllamaDigest = (
    "a2845456d7ad1e2100f620eaad82c3e63860a24330948111f6ad5d8202fd3634"
)
$observedOllamaDigest = ([string]$pinnedModels[0].digest).Replace("sha256:", "")
if ($observedOllamaDigest -ne $expectedOllamaDigest) {
    throw "Ollama model digest mismatch: $observedOllamaDigest"
}
if ($pinnedModels[0].details.quantization_level -ne "Q4_K_M") {
    throw "Ollama model is not Q4_K_M."
}

$ffmpegEncoders = (& ffmpeg -hide_banner -encoders 2>&1 | Out-String)
foreach ($requiredEncoder in @("h264_amf", "hevc_amf")) {
    if ($ffmpegEncoders -notmatch "\b$requiredEncoder\b") {
        throw "The active FFmpeg build does not expose $requiredEncoder."
    }
}

if ([string]::IsNullOrWhiteSpace($OllamaServerLog)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "OllamaServerLog is required when LOCALAPPDATA is unavailable."
    }
    $resolvedOllamaLog = Join-Path $env:LOCALAPPDATA "Ollama\server.log"
} elseif ([System.IO.Path]::IsPathRooted($OllamaServerLog)) {
    $resolvedOllamaLog = [System.IO.Path]::GetFullPath($OllamaServerLog)
} else {
    $resolvedOllamaLog = [System.IO.Path]::GetFullPath(
        (Join-Path $repoRoot $OllamaServerLog)
    )
}
if (-not (Test-Path -LiteralPath $resolvedOllamaLog)) {
    throw "Ollama server log is missing: $resolvedOllamaLog"
}

$huggingFaceRedirect = Join-Path $backendRoot "models\huggingface.redirect"
$huggingFaceCacheCandidate = if (-not [string]::IsNullOrWhiteSpace(
    $env:COLORGRAPH_HUGGINGFACE_CACHE_DIR
)) {
    $env:COLORGRAPH_HUGGINGFACE_CACHE_DIR
} elseif (Test-Path -LiteralPath $huggingFaceRedirect) {
    (Get-Content -LiteralPath $huggingFaceRedirect -Raw -Encoding utf8).Trim()
} else {
    Join-Path $backendRoot "models\huggingface"
}
$huggingFaceCache = if ([System.IO.Path]::IsPathRooted(
    $huggingFaceCacheCandidate
)) {
    [System.IO.Path]::GetFullPath($huggingFaceCacheCandidate)
} else {
    [System.IO.Path]::GetFullPath(
        (Join-Path $backendRoot $huggingFaceCacheCandidate)
    )
}
if (-not (Test-Path -LiteralPath $huggingFaceCache)) {
    throw "Hugging Face cache is unavailable: $huggingFaceCache"
}
foreach ($requiredModel in @(
    @{
        Directory = "models--openai--clip-vit-base-patch32"
        Revision = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
    },
    @{
        Directory = "models--nvidia--segformer-b0-finetuned-ade-512-512"
        Revision = "489d5cd81a0b59fab9b7ea758d3548ebe99677da"
    },
    @{
        Directory = "models--depth-anything--Depth-Anything-V2-Small-hf"
        Revision = "5426e4f0f36572d16453bbda7a8389317b1bef99"
    }
)) {
    $modelDirectory = Join-Path $huggingFaceCache $requiredModel.Directory
    if (-not (Test-Path -LiteralPath $modelDirectory)) {
        throw "Required local model cache is missing: $modelDirectory"
    }
    $snapshotDirectory = Join-Path $modelDirectory (
        "snapshots\" + $requiredModel.Revision
    )
    if (-not (Test-Path -LiteralPath $snapshotDirectory)) {
        throw "Required pinned model snapshot is missing: $snapshotDirectory"
    }
}

New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null
$precisionReport = Join-Path $resolvedOutput "precision-gate-rocm.json"
$fullReport = Join-Path $resolvedOutput "amd-full-pipeline-report.json"
$sourceManifest = Join-Path $repoRoot "output\evidence\bench-001-amd-demo-source\manifest.json"

$env:COLORGRAPH_DEVICE = "rocm"
$env:COLORGRAPH_ENABLE_OLLAMA_CREATIVE_PROVIDER = "true"
$env:COLORGRAPH_OLLAMA_CREATIVE_MODEL = "colorgraph-qwen3.5:9b"
$env:COLORGRAPH_OLLAMA_CREATIVE_MODEL_DIGEST = (
    $expectedOllamaDigest
)
$env:COLORGRAPH_OLLAMA_CREATIVE_RUNTIME_VERSION = $OllamaRuntimeVersion
$env:COLORGRAPH_OLLAMA_CREATIVE_QUANTIZATION = "Q4_K_M"
$env:COLORGRAPH_OLLAMA_CREATIVE_REQUIRE_GPU = "true"
$env:COLORGRAPH_OLLAMA_CREATIVE_MIN_GPU_OFFLOAD_RATIO = "0.99"
$env:COLORGRAPH_OLLAMA_CREATIVE_UNLOAD_AFTER_REQUEST = "true"
$env:COLORGRAPH_OLLAMA_CREATIVE_IMAGE_INPUT = "true"
$env:COLORGRAPH_OLLAMA_CREATIVE_STRICT_OUTPUT = "true"
$env:COLORGRAPH_OLLAMA_CREATIVE_MAX_CONTEXT_TOKENS = "8192"
$env:COLORGRAPH_OLLAMA_CREATIVE_MAX_IMAGES = "1"
$env:COLORGRAPH_OLLAMA_SERVER_LOG = $resolvedOllamaLog
$env:COLORGRAPH_HUGGINGFACE_CACHE_DIR = $huggingFaceCache
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"

Push-Location $backendRoot
try {
    Write-Host "1/3 Verifying the supported ROCm host and media tools..."
    & $colorgraph doctor
    if ($LASTEXITCODE -ne 0) {
        throw "ColorGraph doctor failed."
    }

    Write-Host "2/3 Running the three-repeat ROCm FP32 precision gate..."
    & $colorgraph precision-gate `
        --require-runtime rocm `
        --repeats 3 `
        --output $precisionReport
    if ($LASTEXITCODE -ne 0) {
        throw "The ROCm precision gate failed."
    }

    Write-Host "3/3 Running AI, Ollama ROCm, AMD Demo, Main10 AMF, and hard QA..."
    & $colorgraph amd-full-pipeline `
        $ProjectId `
        --source-manifest $sourceManifest `
        --precision-report $precisionReport `
        --output-dir $resolvedOutput `
        --output $fullReport `
        --batch-size $BatchSize `
        --ollama-server-log $resolvedOllamaLog
    if ($LASTEXITCODE -ne 0) {
        throw "The full AMD pipeline failed. Inspect the console and $resolvedOutput."
    }
} finally {
    Pop-Location
}

Write-Host "Full AMD pipeline passed."
Write-Host "Report: $fullReport"
Write-Host "Report SHA-256: ${fullReport}.sha256"
Write-Host "Final Main10 video: $(Join-Path $resolvedOutput 'final-master-main10.mp4')"
