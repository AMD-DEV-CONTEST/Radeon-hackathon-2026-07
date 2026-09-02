# run_v9.ps1 - Full v9 pipeline (corrected)
#
# Fixes vs v8:
#   - Go validator: injects func main(){} stub for library functions (no more "main undeclared")
#   - Rust prompts: explicit use statements required in system prompt
#   - --mix_general: Alpaca-cleaned 25% blend to prevent catastrophic forgetting
#   - --reset: forces fresh gap generation (no --resume) to pick up fixed validators
#   - Targeted gap samples (determinex_v1_targeted_gaps.jsonl) included in corpus
#   - micro_eval now has 9 concepts (40 probes added: arc_mutex, refcell_borrow,
#     go_panic_recover, go_fmt_errorf, first_even_zero)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = "$root\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts] $msg"
}

Log "=== Determinex v9 Pipeline ==="
Log "Root: $root"

# -- Step 1: Fresh gap pass 1 (no --resume: validators are fixed, retry all failures) --
Log "START gen pass 1 - fresh run with fixed Go validator + Rust use-statement prompts"
$p1Start = Get-Date
python "$root\scripts\generate_gap_curriculum.py"
if ($LASTEXITCODE -ne 0) { Log "ERROR gen pass 1 failed"; exit 1 }
$p1Elapsed = [math]::Round(((Get-Date) - $p1Start).TotalMinutes, 1)
Log "DONE gen pass 1 in ${p1Elapsed}m"

# -- Step 2: Fresh gap pass 2 -------------------------------------------------------
Log "START gen pass 2 - fresh adversarial + C++ + Kotlin"
$p2Start = Get-Date
python "$root\scripts\generate_gap_curriculum_v2.py"
if ($LASTEXITCODE -ne 0) { Log "ERROR gen pass 2 failed"; exit 1 }
$p2Elapsed = [math]::Round(((Get-Date) - $p2Start).TotalMinutes, 1)
Log "DONE gen pass 2 in ${p2Elapsed}m"

# -- Step 3: Unload Leviathan before training ----------------------------------------
Log "Unloading Leviathan from RAM before training..."
try { $null = (ollama stop determinex-leviathan:v1 2>&1) } catch {}
Start-Sleep -Seconds 3
Log "Leviathan unloaded"

# -- Step 4: Train v9 with Alpaca mix ------------------------------------------------
Log "START training v9 - full corpus + Alpaca mix (catastrophic forgetting guard)"
$trainStart = Get-Date
python "$root\train_unsloth.py" --version 9 --mix-general --epochs 3
if ($LASTEXITCODE -ne 0) { Log "ERROR v9 training failed"; exit 1 }
$trainElapsed = [math]::Round(((Get-Date) - $trainStart).TotalMinutes, 1)
Log "DONE v9 training in ${trainElapsed}m"

# -- Step 5: Run expanded micro_eval (9 concepts, 45 probes) -------------------------
Log "START micro_eval on determinex-student:v9 (9 concepts)"
python "$root\scripts\micro_eval.py" --model "determinex-student:v9" --compare
if ($LASTEXITCODE -ne 0) { Log "WARNING micro_eval returned non-zero" }

# -- Step 6: SWE-bench ---------------------------------------------------------------
Log "START SWE-bench on determinex-engineer:v9"
python "$root\scripts\run_swebench.py" --engineer "determinex-engineer:v9" 2>$null
if ($LASTEXITCODE -ne 0) {
    Log "NOTE: run_swebench.py not found or errored - run manually when ready"
}

Log "=== v9 Pipeline Complete ==="
Log "Check logs/eval_results/ for micro_eval results (9 concepts)"
Log "Check .determinex_staging/evals/ for SWE-bench scorecard"
Log "Key gaps to watch: go_fmt_errorf (was 0/5), go_panic_recover, arc_mutex, refcell_borrow"
