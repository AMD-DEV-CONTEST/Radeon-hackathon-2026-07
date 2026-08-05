# ignite_forge.ps1
# Master Orchestrator: The Determinex Forge
# Distillation is now INLINE — Claude fires automatically after each task failure.
# Run this script from the C:\Dev\Determinex directory.

Write-Host "════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "             DETERMINEX FORGE INITIATED                " -ForegroundColor Cyan
Write-Host "════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# Move into the backend to execute Cargo commands
Push-Location .\frontend\src-tauri
try {

    Write-Host "[*] PHASE 1: IGNITING POLYGLOT DYNO + INLINE AUTO-DISTILLATION" -ForegroundColor Yellow
    Write-Host "    Gauntlet runs and Claude distills each failure immediately in background." -ForegroundColor DarkGray
    Write-Host "    By the time the last task finishes, distillation is already done." -ForegroundColor DarkGray
    Write-Host ""

    # Inject all polyglot toolchain paths + Anthropic API key for inline distillation
    $env:PATH = "$env:USERPROFILE\.cargo\bin;C:\msys64\mingw64\bin;C:\Program Files\Go\bin;C:\Program Files\nodejs;$env:LOCALAPPDATA\kotlinc\kotlinc\bin;$env:LOCALAPPDATA\Microsoft\WinGet\Packages\SQLite.SQLite_Microsoft.Winget.Source_8wekyb3d8bbwe;$env:PATH"

    # Load all API keys from .env if not already in environment.
    # DETERMINEX_CLAUDE_MODEL and DETERMINEX_GEMINI_MODEL can be overridden here to
    # update distillation models without recompiling — just edit .env.
    $envFile = Join-Path (Split-Path $PSScriptRoot) ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match "^([A-Z_]+)=(.+)$") {
                $key = $Matches[1]; $val = $Matches[2].Trim().Trim('"')
                if (-not (Get-Item "env:$key" -ErrorAction SilentlyContinue)) {
                    Set-Item "env:$key" $val
                    Write-Host "[*] Loaded $key from .env" -ForegroundColor DarkGray
                }
            }
        }
    }

    # We use ErrorAction Ignore since cargo test exits 1 due to adversarial tasks failing intentionally.
    cargo test --test benchmark_ingestor -- --nocapture 2>&1 | Out-Default

    Write-Host ""
    Write-Host "[+] FORGE COMPLETE." -ForegroundColor Green
    Write-Host "    determinex_v1_distilled_claude.jsonl  -> Claude expert analysis (inline distilled)" -ForegroundColor Green
    Write-Host "    determinex_v1_distilled_gemini.jsonl  -> Gemini expert analysis (inline distilled)" -ForegroundColor Green
    Write-Host "    determinex_v1_distilled_observer.jsonl -> Observer correction data" -ForegroundColor Green
    Write-Host "    Update models anytime: set DETERMINEX_CLAUDE_MODEL or DETERMINEX_GEMINI_MODEL in .env" -ForegroundColor DarkGray

} finally {
    Pop-Location
}
