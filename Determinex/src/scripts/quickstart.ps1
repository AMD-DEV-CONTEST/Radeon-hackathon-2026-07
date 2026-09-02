# quickstart.ps1 - Determinex one-shot bring-up
# Sprint 0 deliverable: doctor + register + smoke in one command.
#
# Usage from repo root:
#   .\scripts\quickstart.ps1            # full chain: doctor, register, smoke
#   .\scripts\quickstart.ps1 -NoSmoke   # stop after registration (safe to run during PB evals)
#   .\scripts\quickstart.ps1 -DoctorOnly
#
# Encoded UTF-8 with BOM so Windows PowerShell 5.1 parses cleanly.

[CmdletBinding()]
param(
    [switch]$DoctorOnly,
    [switch]$NoSmoke,
    [string]$ModelsDir = $env:DETERMINEX_MODELS_DIR,
    [string]$Python311 = "C:\Users\ryang\AppData\Local\Python\pythoncore-3.11-64\python.exe"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Write-Step($msg) { Write-Host "`n[DETERMINEX] $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "  WARN $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  FAIL $msg" -ForegroundColor Red }

# ---------- Resolve DETERMINEX_MODELS_DIR ----------
if (-not $ModelsDir) {
    $envFile = Join-Path $RepoRoot ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match "^DETERMINEX_MODELS_DIR=(.+)$") {
                $ModelsDir = $Matches[1].Trim()
            }
        }
    }
}
if (-not $ModelsDir) { $ModelsDir = "T:/determinex-models" }
$ModelsDir = $ModelsDir.Replace("\", "/")

# ---------- Step 1: doctor ----------
Write-Step "Step 1 of 3 - doctor (env + dependency check)"
if (-not (Test-Path $Python311)) {
    Write-Fail "Python 3.11 not found at $Python311. Edit -Python311 param."
    exit 1
}
Write-OK "Python 3.11 at $Python311"

& $Python311 -c "from llama_cpp import Llama; print('llama_cpp', __import__('llama_cpp').__version__)" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 "llama_cpp import failed. Run: $Python311 -m pip install --force-reinstall --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu llama-cpp-python"
    exit 1
}
Write-OK "llama-cpp-python imports clean"

$doctorScript = Join-Path $RepoRoot "scripts\determinex_doctor.py"
if (Test-Path $doctorScript) {
    & $Python311 $doctorScript
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "determinex_doctor.py reported issues (continuing)" }
}

if ($DoctorOnly) {
    Write-OK "Doctor complete. Exiting (DoctorOnly)."
    exit 0
}

# ---------- Step 2: register models ----------
Write-Step "Step 2 of 3 - register Ollama tags from $ModelsDir"

$models = @(
    @{ Tag = "determinex-engineer-v11-dsl"; Modelfile = "$ModelsDir/versions/engineer/v11-dsl/Modelfile.engineer-v11-dsl" }
    @{ Tag = "determinex-observer-v6-dsl";  Modelfile = "$ModelsDir/versions/observer/v6-dsl/Modelfile.observer-v6-dsl" }
    @{ Tag = "determinex-sentinel-v5-dsl";  Modelfile = "$ModelsDir/versions/sentinel/v5-dsl/Modelfile.sentinel-v5-dsl" }
)

$listOut = ollama list 2>&1 | Out-String
foreach ($m in $models) {
    if ($listOut -match [regex]::Escape($m.Tag)) {
        Write-OK "$($m.Tag) already registered"
        continue
    }
    if (-not (Test-Path $m.Modelfile)) {
        Write-Fail "Modelfile missing: $($m.Modelfile)"
        exit 1
    }
    Write-Host "  Registering $($m.Tag)..." -ForegroundColor White
    ollama create $m.Tag -f $m.Modelfile
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Registration failed for $($m.Tag)"
        exit 1
    }
    Write-OK "$($m.Tag) registered"
}

if ($NoSmoke) {
    Write-OK "Registration complete. Exiting (NoSmoke). Run smoke later with: $Python311 scripts\determinex_hive.py new-session --spec specs\smoke_rust.md --lang rust"
    exit 0
}

# ---------- Step 3: smoke session ----------
Write-Step "Step 3 of 3 - Rust smoke session via Hive pipeline"
Write-Warn2 "Smoke loads ~12 GB GGUFs into VRAM. Abort with Ctrl+C if any GPU-bound work is running."

$specPath = Join-Path $RepoRoot "specs\smoke_rust.md"
if (-not (Test-Path $specPath)) {
    Write-Fail "Smoke spec missing: $specPath"
    exit 1
}

$hivePath = Join-Path $RepoRoot "scripts\determinex_hive.py"
$smokeStart = Get-Date

Write-Host "  new-session..." -ForegroundColor White
$newSession = & $Python311 $hivePath new-session --spec $specPath --lang rust 2>&1
$newSession | ForEach-Object { Write-Host "    $_" }
if ($LASTEXITCODE -ne 0) { Write-Fail "new-session failed"; exit 1 }

$sessionId = ($newSession | Select-String -Pattern "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" | Select-Object -Last 1).Matches.Value
if (-not $sessionId) { Write-Fail "Could not extract session id from new-session output"; exit 1 }
Write-OK "Session: $sessionId"

Write-Host "  generate-dag..." -ForegroundColor White
& $Python311 $hivePath generate-dag --session $sessionId
if ($LASTEXITCODE -ne 0) { Write-Fail "generate-dag failed"; exit 1 }

Write-Host "  run-session..." -ForegroundColor White
& $Python311 $hivePath run-session --session $sessionId
$rc = $LASTEXITCODE

$elapsed = (Get-Date) - $smokeStart
Write-Host ""
Write-Host ("  Elapsed: {0:N1}s" -f $elapsed.TotalSeconds) -ForegroundColor White
if ($rc -eq 0) {
    if ($elapsed.TotalSeconds -lt 60) { Write-OK "Smoke session PASSED. Sprint 0 acceptance: OK" } else { Write-OK "Smoke session PASSED." }
    if ($elapsed.TotalSeconds -ge 60) { Write-Warn2 "Took >=60s. Acceptance criterion not met (target less than 60s on warm cache)." }
} else {
    Write-Fail "Smoke session FAILED (rc=$rc). Session: $sessionId"
    exit $rc
}
