[CmdletBinding()]
param(
    [string]$VenvPath = ".venv-rocm",
    [string]$Python = "3.12"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendRoot = Join-Path $repoRoot "backend"
$requirements = Join-Path $backendRoot "requirements-amd-rocm-windows-7.2.1.txt"
$resolvedVenv = if ([System.IO.Path]::IsPathRooted($VenvPath)) {
    [System.IO.Path]::GetFullPath($VenvPath)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $VenvPath))
}
$venvPython = Join-Path $resolvedVenv "Scripts\python.exe"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required and was not found on PATH."
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    & uv venv $resolvedVenv --python $Python
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the ROCm Python environment."
    }
}

& uv pip install --python $venvPython --no-cache --requirements $requirements
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install the frozen AMD ROCm 7.2.1 environment."
}
& uv pip install --python $venvPython --no-deps --editable $backendRoot
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install ColorGraph into the ROCm environment."
}
& uv pip check --python $venvPython
if ($LASTEXITCODE -ne 0) {
    throw "The ROCm environment contains incompatible package dependencies."
}

$env:COLORGRAPH_DEVICE = "rocm"
& $venvPython -c @"
import json
import sys
import torch
import torchvision

payload = {
    "python_version": ".".join(str(value) for value in sys.version_info[:3]),
    "torch_version": torch.__version__,
    "torchvision_version": torchvision.__version__,
    "hip_version": torch.version.hip,
    "accelerator_available": torch.cuda.is_available(),
    "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
}
print(json.dumps(payload, indent=2))
failures = []
if sys.version_info[:2] != (3, 12):
    failures.append("Python must be 3.12")
if payload["torch_version"] != "2.9.1+rocm7.2.1":
    failures.append("torch must be 2.9.1+rocm7.2.1")
if payload["torchvision_version"] != "0.24.1+rocm7.2.1":
    failures.append("torchvision must be 0.24.1+rocm7.2.1")
if payload["hip_version"] != "7.2.1":
    failures.append("torch.version.hip must be 7.2.1")
if not payload["accelerator_available"]:
    failures.append("PyTorch does not expose an active ROCm device")
if failures:
    raise SystemExit("; ".join(failures))
"@
if ($LASTEXITCODE -ne 0) {
    throw "ROCm PyTorch verification failed."
}

Write-Host "ROCm environment ready: $resolvedVenv"
Write-Host "Next: .\scripts\run-amd-full-pipeline.ps1 -VenvPath `"$resolvedVenv`""
