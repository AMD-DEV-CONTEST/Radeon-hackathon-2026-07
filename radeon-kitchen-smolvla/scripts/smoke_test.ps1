param(
    [string]$Checkpoint = "output/train/smolvla_kitchen_wrist/final",
    [string]$DatasetId = "local/franka-kitchen-wrist-100ep",
    [string]$OutputDir = "output",
    [int]$MaxSteps = 10,
    [switch]$RenderCpu
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "python was not found. Activate the ROCm project environment first."
}
if (-not (Test-Path $Checkpoint)) {
    throw "checkpoint not found: $Checkpoint. Download or train the model before running the smoke test."
}

$validationPath = Join-Path $OutputDir "smoke/dataset_validation.json"
New-Item -ItemType Directory -Force -Path (Split-Path $validationPath) | Out-Null

Write-Host "[smoke] validating LeRobot dataset: $DatasetId"
& python scripts/08_validate_dataset.py --dataset-id $DatasetId --output $validationPath
if ($LASTEXITCODE -ne 0) { throw "dataset validation failed" }

$evalArgs = @(
    "scripts/04_eval_custom_scene.py",
    "--policy-type", "smolvla",
    "--checkpoint", $Checkpoint,
    "--dataset-id", $DatasetId,
    "--task", "Pick up the cube.",
    "--n-episodes", "1",
    "--max-steps", $MaxSteps,
    "--seed", "0",
    "--run-name", "smoke_test",
    "--output-dir", $OutputDir
)
if ($RenderCpu) { $evalArgs += "--render-cpu" }

Write-Host "[smoke] running one-episode inference check"
& python @evalArgs
if ($LASTEXITCODE -ne 0) { throw "inference smoke test failed" }

$summary = Join-Path $OutputDir "eval/smoke_test/eval_summary.json"
if (-not (Test-Path $summary)) { throw "smoke test did not produce $summary" }
Write-Host "[smoke] passed: $summary"
