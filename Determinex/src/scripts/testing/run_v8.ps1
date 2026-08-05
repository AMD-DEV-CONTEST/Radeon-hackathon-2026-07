# run_v8.ps1 - Full v8 pipeline: gen pass 1 (if not done) -> gen pass 2 -> train v8 -> eval
# Run this after gap_curriculum_gen pass 1 finishes, or from scratch.
# Leviathan runs both generation passes back-to-back while warm, then GPU trains once.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = "$root\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts] $msg"
}

Log "=== Determinex v8 Pipeline ==="
Log "Root: $root"

# -- Step 1: Gen pass 1 (skip if already complete) ----------------------------
$gap1Output = "$root\frontend\src-tauri\determinex_v1_gap_curriculum.jsonl"
$gap1Lines  = if (Test-Path $gap1Output) { (Get-Content $gap1Output | Measure-Object -Line).Lines } else { 0 }

if ($gap1Lines -ge 62) {
    Log "SKIP gen pass 1 - already have $gap1Lines samples in gap_curriculum.jsonl"
} else {
    Log "START gen pass 1 - $gap1Lines/62 samples done (resuming)"
    $p1Start = Get-Date
    python "$root\scripts\generate_gap_curriculum.py" --resume
    if ($LASTEXITCODE -ne 0) { Log "ERROR gen pass 1 failed"; exit 1 }
    $p1Elapsed = [math]::Round(((Get-Date) - $p1Start).TotalMinutes, 1)
    Log "DONE gen pass 1 in ${p1Elapsed}m"
}

# -- Step 2: Gen pass 2 (adversarial + C++ + Kotlin) --------------------------
Log "START gen pass 2 - adversarial variants + C++ + Kotlin (resuming if partial)"
$p2Start = Get-Date
python "$root\scripts\generate_gap_curriculum_v2.py" --resume
if ($LASTEXITCODE -ne 0) { Log "ERROR gen pass 2 failed"; exit 1 }
$p2Elapsed = [math]::Round(((Get-Date) - $p2Start).TotalMinutes, 1)
Log "DONE gen pass 2 in ${p2Elapsed}m"

# -- Step 3: Unload Leviathan before training ----------------------------------
Log "Unloading Leviathan from RAM before training..."
try { $null = (ollama stop determinex-leviathan:v1 2>&1) } catch {}
Start-Sleep -Seconds 3
Log "Leviathan unloaded"

# -- Step 4: Train v8 ----------------------------------------------------------
Log "START training v8 - full corpus"
$trainStart = Get-Date
python "$root\train_unsloth.py" --version 8
if ($LASTEXITCODE -ne 0) { Log "ERROR v8 training failed"; exit 1 }
$trainElapsed = [math]::Round(((Get-Date) - $trainStart).TotalMinutes, 1)
Log "DONE v8 training in ${trainElapsed}m"

# -- Step 5: micro_eval --------------------------------------------------------
Log "START micro_eval on determinex-student:v8"
python "$root\scripts\micro_eval.py" --model "determinex-student:v8"
if ($LASTEXITCODE -ne 0) { Log "WARNING micro_eval returned non-zero" }

# -- Step 6: SWE-bench ---------------------------------------------------------
Log "START SWE-bench on determinex-engineer:v8"
python "$root\scripts\run_swebench.py" --engineer "determinex-engineer:v8" 2>$null
if ($LASTEXITCODE -ne 0) {
    Log "NOTE: run_swebench.py not found or errored - run manually when ready"
}

Log "=== v8 Pipeline Complete ==="
Log "Check logs/eval_results/ for micro_eval results"
Log "Check .determinex_staging/evals/ for SWE-bench scorecard"
