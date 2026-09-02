# overnight_v6.ps1  -  Determinex Overnight Pipeline
# Run AFTER v5 training completes.
# Step 1: Convert 276 failure records to compile-validated SFT pairs  (~2h)
# Step 2: v6 training on full corpus with new failure fixes             (~1h)
# Step 3: Quick eval
#
# Usage (from C:\Dev\Determinex):
#   .\overnight_v6.ps1

$ErrorActionPreference = "Stop"
$Root      = $PSScriptRoot
$StartTime = Get-Date

function Log   { param($m); Write-Host ("[" + (Get-Date -Format "HH:mm:ss") + "] " + $m) -ForegroundColor Cyan }
function LogOk { param($m); Write-Host ("[" + (Get-Date -Format "HH:mm:ss") + "] [OK]   " + $m) -ForegroundColor Green }
function LogWn { param($m); Write-Host ("[" + (Get-Date -Format "HH:mm:ss") + "] [WARN] " + $m) -ForegroundColor Yellow }
function LogErr{ param($m); Write-Host ("[" + (Get-Date -Format "HH:mm:ss") + "] [FAIL] " + $m) -ForegroundColor Red }

# ---- Paths ------------------------------------------------------------------
$InputFile     = Join-Path $Root "frontend\src-tauri\determinex_v1_failures.jsonl"
$OutputFile    = Join-Path $Root "frontend\src-tauri\determinex_v1_failures_sft.jsonl"
$ConvertScript = Join-Path $Root "scripts\convert_failures_to_sft.py"
$TrainScript   = Join-Path $Root "train_unsloth.py"

Log "=== DETERMINEX OVERNIGHT PIPELINE STARTING ==="
Log "Root: $Root"

foreach ($f in @($InputFile, $ConvertScript, $TrainScript)) {
    if (-not (Test-Path $f)) { LogErr "Not found: $f"; exit 1 }
}

# ---- Check Ollama -----------------------------------------------------------
Log "Checking Ollama..."
try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 -UseBasicParsing | Out-Null
    LogOk "Ollama is alive"
} catch {
    LogErr "Ollama not responding. Run: ollama serve"
    exit 1
}

# ---- STEP 1: Convert failures -> SFT ----------------------------------------
Log ""
Log "=== STEP 1: Failures corpus conversion ==="
Log "276 records  |  Rust/Go compile-validated  |  ~2 hours  |  GPU idle"
Log ""

$ExistingCount = 0
if (Test-Path $OutputFile) {
    $ExistingCount = (Get-Content $OutputFile | Where-Object { $_.Trim() -ne "" }).Count
    if ($ExistingCount -gt 0) {
        LogWn "Output already has $ExistingCount samples -- resuming from where it left off"
    }
}

if ($ExistingCount -gt 0) {
    python scripts\convert_failures_to_sft.py --resume
} else {
    python scripts\convert_failures_to_sft.py
}

if ($LASTEXITCODE -ne 0) {
    LogErr "Conversion failed (exit $LASTEXITCODE). Re-run: python scripts\convert_failures_to_sft.py --resume"
    exit 1
}

$SftCount = 0
if (Test-Path $OutputFile) {
    $SftCount = (Get-Content $OutputFile | Where-Object { $_.Trim() -ne "" }).Count
}
LogOk "Conversion done: $SftCount validated SFT samples in determinex_v1_failures_sft.jsonl"

if ($SftCount -lt 50) {
    LogWn "Low yield ($SftCount samples) -- check scripts\failures_conversion_report.json"
    LogWn "Continuing anyway -- training will skip the file if count is below gate"
}

# ---- STEP 2: Unload Leviathan before GPU training ----------------------------
Log ""
Log "Unloading Leviathan from RAM before GPU training..."
try {
    $body = '{"model":"determinex-leviathan:v1","keep_alive":0}'
    Invoke-WebRequest -Uri "http://localhost:11434/api/generate" `
        -Method POST -Body $body -ContentType "application/json" `
        -TimeoutSec 15 -UseBasicParsing | Out-Null
    LogOk "Leviathan unloaded"
} catch {
    LogWn "Could not unload Leviathan (may already be unloaded -- continuing)"
}
Start-Sleep -Seconds 5

# ---- STEP 2: v6 Training ----------------------------------------------------
Log ""
Log "=== STEP 2: Engineer v6 Training ==="
Log "Corpus: 641 curriculum + $SftCount failure fixes + 213 Alpaca general"
Log "Config: epochs=2  seq=512  batch=1x4  mix-general 75/25  throttle=150ms"
Log ""

python train_unsloth.py `
    --version 6 `
    --epochs 2 `
    --max_seq_length 512 `
    --per_device_batch_size 1 `
    --grad_accum 4 `
    --mix-general `
    --curriculum-ratio 0.75

if ($LASTEXITCODE -ne 0) {
    LogErr "v6 training failed (exit $LASTEXITCODE)"
    LogErr "Retry: python train_unsloth.py --version 6 --epochs 2 --max_seq_length 512 --per_device_batch_size 1 --grad_accum 4 --mix-general --curriculum-ratio 0.75"
    exit 1
}
LogOk "v6 training complete"

# ---- STEP 3: Eval -----------------------------------------------------------
Log ""
Log "=== STEP 3: Eval ==="

$ollamaModels = ollama list 2>&1
if ($ollamaModels -match "determinex-student") {
    python scripts\micro_eval.py --model determinex-student:trained 2>&1
    LogOk "Eval done -- check scores above"
} else {
    LogWn "determinex-student:trained not in Ollama yet"
    LogWn "Manual: ollama create determinex-student:trained -f Modelfile.engineer.v6"
}

# ---- Done -------------------------------------------------------------------
$Elapsed = [math]::Round(((Get-Date) - $StartTime).TotalMinutes, 1)
Log ""
LogOk "=== OVERNIGHT PIPELINE COMPLETE === ($Elapsed min total)"
LogOk "Check in the morning:"
LogOk "  scripts\failures_conversion_report.json"
LogOk "  scripts\fine_tuning\outputs\determinex-engineer-v6\"
LogOk "  latest eval JSON in scripts\"
