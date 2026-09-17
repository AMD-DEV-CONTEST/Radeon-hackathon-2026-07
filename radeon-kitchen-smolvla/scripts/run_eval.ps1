param(
    [int]$Seed = 99,
    [int]$Episodes = 20,
    [int]$MaxSteps = 150,
    [string]$Checkpoint = "output/train/smolvla_kitchen_wrist/final",
    [string]$DatasetId = "local/franka-kitchen-wrist-100ep",
    [string]$Manifest = "",
    [ValidateSet("nominal", "brightness", "noise", "camera_dropout", "occlusion", "delay", "friction_low", "friction_high")]
    [string]$Condition = "nominal",
    [ValidateSet("both", "overhead_only", "wrist_only")]
    [string]$CameraAblation = "both",
    [string]$OutputDir = "output",
    [switch]$RenderCpu,
    [switch]$Uncertainty
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$safeCondition = $Condition.Replace("-", "_")
$runName = "eval_seed${Seed}_${safeCondition}_${CameraAblation}"
$argsList = @(
    "scripts/04_eval_custom_scene.py",
    "--policy-type", "smolvla",
    "--checkpoint", $Checkpoint,
    "--dataset-id", $DatasetId,
    "--task", "Pick up the cube.",
    "--camera-layout", "up_wrist",
    "--camera-ablation", $CameraAblation,
    "--n-episodes", $Episodes,
    "--max-steps", $MaxSteps,
    "--seed", $Seed,
    "--run-name", $runName,
    "--output-dir", $OutputDir
)

if ($Manifest -ne "") { $argsList += "--episode-manifest"; $argsList += $Manifest }
switch ($Condition) {
    "brightness" { $argsList += @("--brightness-range", "0.85", "1.15") }
    "noise" { $argsList += @("--image-noise-std", "4") }
    "camera_dropout" { $argsList += @("--camera-dropout-prob", "0.5") }
    "occlusion" { $argsList += @("--occlusion-prob", "1.0", "--occlusion-fraction", "0.25") }
    "delay" { $argsList += @("--action-delay-steps", "2") }
    "friction_low" { $argsList += @("--cube-friction", "1.2") }
    "friction_high" { $argsList += @("--cube-friction", "1.8") }
}
if ($Uncertainty) {
    $argsList += @(
        "--uncertainty-samples", "3",
        "--uncertainty-threshold", "0.03",
        "--uncertainty-slowdown", "0.5",
        "--uncertainty-replan"
    )
}
if ($RenderCpu) { $argsList += "--render-cpu" }

Write-Host "[eval] condition=$Condition seed=$Seed episodes=$Episodes"
& python @argsList
if ($LASTEXITCODE -ne 0) { throw "evaluation failed" }

$summary = Join-Path $OutputDir "eval/$runName/eval_summary.json"
Write-Host "[eval] result: $summary"
