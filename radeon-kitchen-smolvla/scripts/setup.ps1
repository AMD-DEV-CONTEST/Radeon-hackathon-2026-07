param(
    [switch]$Install,
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Invoke-PythonCheck([string]$Code) {
    & $PythonCommand -c $Code
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency check failed. Install the ROCm-compatible environment first."
    }
}

if (-not (Get-Command $PythonCommand -ErrorAction SilentlyContinue)) {
    throw "Python executable '$PythonCommand' was not found. Activate the project environment first."
}

Write-Host "[setup] repository: $repoRoot"
& $PythonCommand --version

if ($Install) {
    Write-Host "[setup] installing Python requirements from requirements.txt"
    & $PythonCommand -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

Invoke-PythonCheck "import torch; print('[setup] torch', torch.__version__, 'cuda=', torch.cuda.is_available())"
Invoke-PythonCheck "import genesis; print('[setup] genesis import: ok')"
Invoke-PythonCheck "import lerobot; print('[setup] lerobot import: ok')"
Invoke-PythonCheck "import transformers; print('[setup] transformers', transformers.__version__)"

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Host "[setup] ffmpeg: $((Get-Command ffmpeg).Source)"
} else {
    Write-Warning "ffmpeg was not found; video recording will be unavailable."
}

Write-Host "[setup] environment checks passed"
Write-Host "[setup] next: .\scripts\smoke_test.ps1"
