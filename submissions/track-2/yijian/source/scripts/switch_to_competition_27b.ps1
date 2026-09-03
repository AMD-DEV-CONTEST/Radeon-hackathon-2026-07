param(
    [int]$Port = 8600
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# Close only the temporary preview process and restore the known-good W7900
# service before restarting the local workbench with its stable configuration.
ssh radeon-yijian "pkill -f '[s]erve_lora_transformers.py' || true; /workspace/yijian/lora-question-first-v2-lr3e5/bin/restore_27b.sh"
if ($LASTEXITCODE -ne 0) { throw "The W7900 27B recovery command failed." }

Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 300

& (Join-Path $PSScriptRoot "start_competition_27b.ps1") -Port $Port
